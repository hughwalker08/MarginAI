-- Who may query which connected store. The synthetic demo store is open to everyone.
-- kind 'email': that exact address; kind 'domain': any verified address at exactly that domain (no subdomains).
CREATE TABLE store_access (
    store_slug  text NOT NULL REFERENCES stores (slug) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('email', 'domain')),
    value       text NOT NULL CHECK (value = lower(value)),
    added_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (store_slug, kind, value)
);
REVOKE ALL ON store_access FROM PUBLIC, marginai_readonly;

-- Audit trail: which signed-in user asked what.
ALTER TABLE query_log ADD COLUMN user_email text;
