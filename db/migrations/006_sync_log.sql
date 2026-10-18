-- One row per Shopify sync run (initial or incremental), for visibility and debugging.
CREATE TABLE sync_log (
    log_id         bigserial PRIMARY KEY,
    store_slug     text NOT NULL REFERENCES stores (slug) ON DELETE CASCADE,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    mode           text NOT NULL CHECK (mode IN ('full', 'incremental')),
    status         text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'error')),
    orders_synced  integer,
    error          text
);
REVOKE ALL ON sync_log FROM PUBLIC, marginai_readonly;
