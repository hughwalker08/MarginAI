"""Apply SQL migrations in db/migrations/ in filename order, once each.

Usage: python -m db.migrate
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS = Path(__file__).parent / "migrations"


def migrate(database_url: str) -> list[str]:
    applied_now = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


if __name__ == "__main__":
    load_dotenv()
    applied = migrate(os.environ.get("DATABASE_URL", "postgresql:///marginai"))
    print("Applied:", ", ".join(applied) if applied else "nothing (up to date)")
