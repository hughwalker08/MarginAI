-- Every question the engine handles is logged here (question, query, error, latency, cost).
CREATE TABLE query_log (
    log_id         bigserial PRIMARY KEY,
    created_at     timestamptz NOT NULL DEFAULT now(),
    question       text NOT NULL,
    sql            text,
    answer         text,
    error          text,
    attempts       integer NOT NULL DEFAULT 0,
    row_count      integer,
    latency_ms     integer,
    input_tokens   integer,
    output_tokens  integer,
    cost_usd       numeric(12,6),
    model          text
);

-- The query engine's read-only role must only ever see business data.
REVOKE ALL ON query_log, schema_migrations FROM marginai_readonly;
