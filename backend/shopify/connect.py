"""Connect a store whose app lives in the same Shopify organisation (client credentials grant). No browser,
tunnel or install link: the app must already be installed on the store.

  python -m backend.shopify.connect --shop saarde.myshopify.com --slug saarde
reads SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET from .env (the credentials of the app installed on that store).
"""
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from .. import auth
from ..stores import create_store
from . import oauth, vault


def connect(database_url: str, shop: str, slug: str, client_id: str, client_secret: str) -> tuple[str, list[str]]:
    shop = oauth.valid_shop(shop)
    tokens = oauth.client_credentials_token(shop, client_id, client_secret)
    info = oauth.graphql(shop, tokens.access_token, "{ shop { name currencyCode ianaTimezone } }")["shop"]
    scopes = [s["handle"] for s in oauth.graphql(
        shop, tokens.access_token, "{ currentAppInstallation { accessScopes { handle } } }"
    )["currentAppInstallation"]["accessScopes"]]
    store = create_store(database_url, slug, info["name"], shop, info["ianaTimezone"], info["currencyCode"])
    vault.save_tokens(database_url, store.slug, tokens, "client_credentials", client_id, client_secret)
    return store.name, scopes


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--allow-domain", action="append", default=[], help="let everyone at this email domain open the store")
    ap.add_argument("--allow-email", action="append", default=[], help="let this email address open the store")
    args = ap.parse_args()
    name, scopes = connect(os.environ.get("DATABASE_URL", "postgresql:///marginai"), args.shop, args.slug,
                           os.environ["SHOPIFY_CLIENT_ID"], os.environ["SHOPIFY_CLIENT_SECRET"])
    print(f"Connected {name} as '{args.slug}'. Granted scopes: {', '.join(scopes) or '(none)'}")
    db = os.environ.get("DATABASE_URL", "postgresql:///marginai")
    for d in args.allow_domain:
        auth.add_access(db, args.slug, "domain", d)
        print(f"Access: anyone at @{d.lstrip('@').lower()} can open {args.slug}")
    for e in args.allow_email:
        auth.add_access(db, args.slug, "email", e)
        print(f"Access: {e.lower()} can open {args.slug}")
    if not (args.allow_domain or args.allow_email):
        print("No access rules added: only ADMIN_EMAILS can open this store. See: python -m backend.access add")


if __name__ == "__main__":
    main()
