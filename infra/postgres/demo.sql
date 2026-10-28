-- DeepTune demo schema. Runs in both the target DB and the shadow DB so that
-- hypothetical indexes can be validated against an identical plan shape.
-- The target's read-only role is created separately by init.sh/grants.sql.

CREATE TABLE IF NOT EXISTS customers (
    id         bigserial PRIMARY KEY,
    email      text NOT NULL UNIQUE,
    country    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    id       bigserial PRIMARY KEY,
    sku      text NOT NULL UNIQUE,
    name     text NOT NULL,
    category text NOT NULL,
    price_cents integer NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id          bigserial PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES customers(id),
    status      text NOT NULL,
    total_cents integer NOT NULL,
    created_at  timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id         bigserial PRIMARY KEY,
    order_id   bigint NOT NULL REFERENCES orders(id),
    product_id bigint NOT NULL REFERENCES products(id),
    quantity   integer NOT NULL,
    unit_cents integer NOT NULL
);

INSERT INTO customers (email, country, created_at)
SELECT
    'user' || g || '@example.com',
    (ARRAY['US', 'GB', 'DE', 'IN', 'BR'])[1 + (g % 5)],
    now() - ((g % 720) || ' days')::interval
FROM generate_series(1, 20000) AS g
ON CONFLICT (email) DO NOTHING;

INSERT INTO products (sku, name, category, price_cents)
SELECT
    'SKU-' || lpad(g::text, 6, '0'),
    'Product ' || g,
    (ARRAY['books', 'electronics', 'home', 'outdoors'])[1 + (g % 4)],
    500 + (g % 25000)
FROM generate_series(1, 5000) AS g
ON CONFLICT (sku) DO NOTHING;

INSERT INTO orders (customer_id, status, total_cents, created_at)
SELECT
    1 + (g % 20000),
    (ARRAY['paid', 'pending', 'cancelled', 'refunded'])[1 + (g % 4)],
    500 + (g % 40000),
    now() - ((g % 365) || ' days')::interval
FROM generate_series(1, 120000) AS g
WHERE NOT EXISTS (SELECT 1 FROM orders);

INSERT INTO order_items (order_id, product_id, quantity, unit_cents)
SELECT
    o.id,
    1 + (o.id % 5000),
    1 + (o.id % 4),
    o.total_cents
FROM orders AS o
WHERE NOT EXISTS (SELECT 1 FROM order_items);

-- Reviewer mandate: fresh statistics before any plan is compared. This runs
-- once at container init, never against the read-only target from the API.
VACUUM ANALYZE;
