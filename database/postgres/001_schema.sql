-- PostgreSQL 业务表和 AI 只读视图。
-- 请先创建 enterpriseAgent 数据库，并连接到该数据库后执行本脚本。

CREATE TABLE IF NOT EXISTS sales_orders (
    order_id BIGINT PRIMARY KEY,
    order_date DATE NOT NULL,
    department_id VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    amount NUMERIC(18, 2) NOT NULL CHECK (amount >= 0),
    status VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_snapshots (
    snapshot_date DATE NOT NULL,
    department_id VARCHAR(64) NOT NULL,
    warehouse_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    quantity_on_hand INTEGER NOT NULL CHECK (quantity_on_hand >= 0),
    quantity_in_transit INTEGER NOT NULL CHECK (quantity_in_transit >= 0),
    PRIMARY KEY (snapshot_date, department_id, warehouse_id, product_id)
);

-- AI 账号只能查询这两个稳定视图，不直接访问原始业务表。
CREATE OR REPLACE VIEW v_ai_sales_orders AS
SELECT
    order_id,
    order_date,
    department_id,
    region,
    customer_id,
    product_id,
    quantity,
    amount
FROM sales_orders
WHERE status = 'confirmed';

CREATE OR REPLACE VIEW v_ai_inventory_snapshots AS
SELECT
    snapshot_date,
    department_id,
    warehouse_id,
    product_id,
    quantity_on_hand,
    quantity_in_transit
FROM inventory_snapshots;

-- PostgreSQL 没有 CREATE ROLE IF NOT EXISTS，使用 DO 块保证脚本可重复执行。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN
        EXECUTE 'CREATE ROLE agent_ro LOGIN PASSWORD ''agent_ro''';
    ELSE
        EXECUTE 'ALTER ROLE agent_ro WITH LOGIN PASSWORD ''agent_ro''';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE "enterpriseAgent" TO agent_ro;
GRANT USAGE ON SCHEMA public TO agent_ro;
GRANT SELECT ON public.v_ai_sales_orders TO agent_ro;
GRANT SELECT ON public.v_ai_inventory_snapshots TO agent_ro;
