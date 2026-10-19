"""Manage who can query each store.

  python -m backend.access add saarde --domain saarde.com
  python -m backend.access add saarde --email someone@gmail.com
  python -m backend.access remove saarde --domain saarde.com
  python -m backend.access list
"""
import argparse
import os

from dotenv import load_dotenv

from . import auth


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add", "remove"):
        p = sub.add_parser(name)
        p.add_argument("store")
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--email")
        g.add_argument("--domain")
    sub.add_parser("list")
    args = ap.parse_args()
    db = os.environ.get("DATABASE_URL", "postgresql:///marginai")
    if args.cmd == "list":
        rows = auth.list_access(db)
        print("\n".join(f"{s}  {k:6s} {v}" for s, k, v in rows) or "(no rules yet: only admins can open real stores)")
        print("admins (all stores):", ", ".join(sorted(auth.admin_emails())) or "(none)")
        return
    kind, value = ("email", args.email) if args.email else ("domain", args.domain)
    (auth.add_access if args.cmd == "add" else auth.remove_access)(db, args.store, kind, value)
    print(f"{args.cmd}: {args.store} {kind} {value}")


if __name__ == "__main__":
    main()
