"""Static checks on LLM-written SQL. This is the first line of defence; the read-only
Postgres role in executor.py is the hard backstop."""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"locations", "products", "variants", "customers", "discounts", "orders",
                  "order_lines", "refunds", "refund_lines"}

_FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
                    exp.Command, exp.Set, exp.Merge, exp.Copy, exp.TruncateTable, exp.Into,
                    exp.Lock, exp.Grant, exp.Use, exp.Transaction, exp.Commit, exp.Rollback)
_FORBIDDEN_FUNC_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "current_setting", "txid_",
                            "query_to_xml", "xpath", "version", "current_user", "session_user")


# Columns whose values are a fixed set, used to catch typos in generated filters.
ENUM_VALUES = {
    "financial_status": {"paid", "partially_refunded", "refunded", "voided"},
    "sales_channel": {"online", "pos"},
    "kind": {"percentage", "fixed_amount", "free_shipping"},
}


class ValidationError(ValueError):
    pass


def validate_sql(sql: str) -> str:
    """Return the cleaned SQL (no trailing semicolon) or raise ValidationError."""
    if not sql or not sql.strip():
        raise ValidationError("Empty query.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise ValidationError(f"SQL syntax error: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise ValidationError("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise ValidationError("Only SELECT queries are allowed.")

    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise ValidationError(f"{type(node).__name__} is not allowed; queries are read-only.")
        if isinstance(node, exp.Table):
            name = node.name.lower()
            if node.args.get("db") or node.args.get("catalog"):
                raise ValidationError("Schema-qualified tables are not allowed; use plain table names.")
            if name not in ALLOWED_TABLES and name not in cte_names:
                raise ValidationError(
                    f"Unknown table '{node.name}'. Available tables: {', '.join(sorted(ALLOWED_TABLES))}.")
        if isinstance(node, (exp.Anonymous, exp.Func)):
            fname = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if fname.startswith(_FORBIDDEN_FUNC_PREFIXES):
                raise ValidationError(f"Function '{fname}' is not allowed.")
    return sql.strip().rstrip(";").strip()


def semantic_warnings(sql: str, question: str = "") -> list[str]:
    """Mistakes that are legal SQL but give wrong business answers. The engine feeds these back to the model
    for one fix attempt instead of running the query."""
    if re.search(r"void|cancel", question, re.I):
        return []
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return []
    warnings = []
    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    tables = {t.name.lower() for t in tree.find_all(exp.Table)} - cte_names
    if "order_lines" in tables and "orders" not in tables:
        warnings.append("This query reads order_lines without joining orders, so voided orders are counted. JOIN "
                        "orders and filter orders.financial_status <> 'voided'.")
    # A typo in a status literal (e.g. 'voidged') silently matches nothing, so the filter does nothing.
    for col in tree.find_all(exp.Column):
        allowed = ENUM_VALUES.get(col.name.lower())
        parent = col.parent
        if not allowed or not isinstance(parent, (exp.EQ, exp.NEQ, exp.In)):
            continue
        literals = ([parent.expression] if isinstance(parent, (exp.EQ, exp.NEQ)) else parent.expressions)
        for lit in literals:
            if isinstance(lit, exp.Literal) and lit.is_string and lit.this not in allowed:
                warnings.append(f"'{lit.this}' is not a value of {col.name}. It must be one of: "
                                f"{', '.join(sorted(allowed))}.")
    return warnings
