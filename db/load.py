"""Load generated CSVs into Postgres (truncates the data tables first).

Usage: python -m db.load [--csv data_gen/output]
"""
import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Parents before children (foreign keys).
TABLES = ["locations", "products", "variants", "customers", "discounts", "orders",
          "order_lines", "refunds", "refund_lines"]


def load(database_url: str, csv_dir: Path) -> dict[str, int]:
    counts = {}
    with psycopg.connect(database_url) as conn:
        conn.execute("TRUNCATE " + ", ".join(reversed(TABLES)))
        for table in TABLES:
            with (csv_dir / f"{table}.csv").open("rb") as f, \
                    conn.cursor().copy(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)") as copy:
                while chunk := f.read(1 << 20):
                    copy.write(chunk)
            counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return counts


if __name__ == "__main__":
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path(__file__).parents[1] / "data_gen" / "output")
    args = ap.parse_args()
    for t, n in load(os.environ.get("DATABASE_URL", "postgresql:///marginai"), args.csv).items():
        print(f"{t:14s} {n:>7,}")
