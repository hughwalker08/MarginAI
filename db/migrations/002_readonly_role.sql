-- Read-only role for the query engine: the hard safety backstop. Even if a
-- generated query slips past the validator, this role cannot write anything.
-- The role is created without a login; set a password out-of-band:
--   ALTER ROLE marginai_readonly LOGIN PASSWORD '...';

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marginai_readonly') THEN
        CREATE ROLE marginai_readonly NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO marginai_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO marginai_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO marginai_readonly;

ALTER ROLE marginai_readonly SET default_transaction_read_only = on;
ALTER ROLE marginai_readonly SET statement_timeout = '10s';
