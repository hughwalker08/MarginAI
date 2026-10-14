-- MarginAI core schema: a Shopify-shaped store (orders, line items, products,
-- variants, customers, discounts, refunds, locations).
-- Money is AUD and GST-inclusive. Timestamps are timestamptz (stored in UTC).

CREATE TABLE locations (
    location_id   integer PRIMARY KEY,
    name          text NOT NULL,
    type          text NOT NULL CHECK (type IN ('online', 'pos'))
);

CREATE TABLE products (
    product_id    integer PRIMARY KEY,
    title         text NOT NULL,
    product_type  text,
    vendor        text,
    status        text NOT NULL,
    created_at    timestamptz NOT NULL
);

CREATE TABLE variants (
    variant_id    integer PRIMARY KEY,
    product_id    integer NOT NULL REFERENCES products,
    sku           text NOT NULL,
    size          text,
    color         text,
    price         numeric(10,2) NOT NULL,
    cost          numeric(10,2)
);

CREATE TABLE customers (
    customer_id        integer PRIMARY KEY,
    first_name         text,
    last_name          text,
    email              text,
    city               text,
    state              text,
    accepts_marketing  boolean NOT NULL,
    created_at         timestamptz NOT NULL
);

CREATE TABLE discounts (
    discount_id   integer PRIMARY KEY,
    code          text NOT NULL,
    title         text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('percentage', 'fixed_amount', 'free_shipping')),
    value         numeric(10,2),
    is_automatic  boolean NOT NULL,
    starts_on     date NOT NULL,
    ends_on       date
);

CREATE TABLE orders (
    order_id          integer PRIMARY KEY,
    order_number      integer NOT NULL,
    customer_id       integer REFERENCES customers,
    location_id       integer NOT NULL REFERENCES locations,
    sales_channel     text NOT NULL CHECK (sales_channel IN ('online', 'pos')),
    discount_id       integer REFERENCES discounts,
    created_at        timestamptz NOT NULL,
    financial_status  text NOT NULL
        CHECK (financial_status IN ('paid', 'partially_refunded', 'refunded', 'voided')),
    subtotal          numeric(10,2) NOT NULL,
    discount_total    numeric(10,2) NOT NULL,
    shipping_total    numeric(10,2) NOT NULL,
    tax_total         numeric(10,2) NOT NULL,
    total             numeric(10,2) NOT NULL,
    shipping_state    text
);

CREATE TABLE order_lines (
    order_line_id  integer PRIMARY KEY,
    order_id       integer NOT NULL REFERENCES orders,
    variant_id     integer NOT NULL REFERENCES variants,
    quantity       integer NOT NULL CHECK (quantity > 0),
    unit_price     numeric(10,2) NOT NULL,
    line_discount  numeric(10,2) NOT NULL
);

CREATE TABLE refunds (
    refund_id    integer PRIMARY KEY,
    order_id     integer NOT NULL REFERENCES orders,
    created_at   timestamptz NOT NULL,
    reason       text,
    restocked    boolean NOT NULL,
    amount       numeric(10,2) NOT NULL
);

CREATE TABLE refund_lines (
    refund_line_id  integer PRIMARY KEY,
    refund_id       integer NOT NULL REFERENCES refunds,
    order_line_id   integer NOT NULL REFERENCES order_lines,
    quantity        integer NOT NULL CHECK (quantity > 0),
    amount          numeric(10,2) NOT NULL
);

CREATE INDEX orders_created_at_idx   ON orders (created_at);
CREATE INDEX orders_customer_idx     ON orders (customer_id);
CREATE INDEX order_lines_order_idx   ON order_lines (order_id);
CREATE INDEX order_lines_variant_idx ON order_lines (variant_id);
CREATE INDEX variants_product_idx    ON variants (product_id);
CREATE INDEX refunds_order_idx       ON refunds (order_id);
