-- Multi-store support. Each connected store's data lives in its own Postgres schema (same tables as
-- `public`, which holds the synthetic demo store) and is queried through its own read-only role, so a
-- question about one store can never read another's rows even if the validator were bypassed.

CREATE TABLE stores (
    slug            text PRIMARY KEY CHECK (slug ~ '^[a-z][a-z0-9_]{2,29}$'),
    name            text NOT NULL,
    shop_domain     text UNIQUE,
    schema_name     text NOT NULL UNIQUE,
    role_name       text NOT NULL UNIQUE,
    timezone        text NOT NULL DEFAULT 'Australia/Sydney',
    currency        text NOT NULL DEFAULT 'AUD',
    tax_name        text NOT NULL DEFAULT 'GST',
    tax_divisor     numeric(6,4) NOT NULL DEFAULT 1.1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_synced_at  timestamptz
);

-- Shopify access tokens, encrypted by the application (Fernet) before they reach this table.
CREATE TABLE shopify_tokens (
    store_slug          text PRIMARY KEY REFERENCES stores (slug) ON DELETE CASCADE,
    access_token_enc    text NOT NULL,
    refresh_token_enc   text,
    expires_at          timestamptz,
    refresh_expires_at  timestamptz,
    scope               text NOT NULL,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE query_log ADD COLUMN store text;

REVOKE ALL ON stores, shopify_tokens FROM PUBLIC, marginai_readonly;
