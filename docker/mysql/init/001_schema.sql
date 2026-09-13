CREATE TABLE IF NOT EXISTS sales_orders (
    order_id BIGINT PRIMARY KEY,
    order_date DATE NOT NULL,
    department_id VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    quantity INT NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    status VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_snapshots (
    snapshot_date DATE NOT NULL,
    department_id VARCHAR(64) NOT NULL,
    warehouse_id VARCHAR(64) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    quantity_on_hand INT NOT NULL,
    quantity_in_transit INT NOT NULL,
    PRIMARY KEY (snapshot_date, department_id, warehouse_id, product_id)
);

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

CREATE USER IF NOT EXISTS 'agent_ro'@'%' IDENTIFIED BY 'agent_ro';
GRANT SELECT ON enterprise_demo.v_ai_sales_orders TO 'agent_ro'@'%';
GRANT SELECT ON enterprise_demo.v_ai_inventory_snapshots TO 'agent_ro'@'%';
FLUSH PRIVILEGES;
