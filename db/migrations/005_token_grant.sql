-- Stores can connect two ways: the OAuth install flow (a refresh token renews access), or the client
-- credentials grant (the app and store are in the same Shopify organisation; the app's own client id and
-- secret, kept encrypted, are used to request a fresh 24-hour token whenever one is needed).
ALTER TABLE shopify_tokens
    ADD COLUMN grant_type text NOT NULL DEFAULT 'authorization_code'
        CHECK (grant_type IN ('authorization_code', 'client_credentials')),
    ADD COLUMN client_id text,
    ADD COLUMN client_secret_enc text;
