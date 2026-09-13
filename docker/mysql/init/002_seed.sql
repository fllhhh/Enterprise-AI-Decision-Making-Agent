INSERT IGNORE INTO sales_orders
    (order_id, order_date, department_id, region, customer_id, product_id, quantity, amount, status)
VALUES
    (1001, '2026-07-03', 'sales', 'east', 'C-A', 'P-1001', 20, 18000.00, 'confirmed'),
    (1002, '2026-07-08', 'sales', 'east', 'C-B', 'P-1002', 12, 12600.00, 'confirmed'),
    (1003, '2026-07-15', 'sales', 'south', 'C-C', 'P-1001', 30, 27000.00, 'confirmed'),
    (1004, '2026-07-22', 'sales', 'north', 'C-D', 'P-1003', 8, 9600.00, 'confirmed'),
    (1005, '2026-07-28', 'sales', 'east', 'C-E', 'P-1002', 25, 26250.00, 'cancelled'),
    (2001, '2026-07-11', 'finance', 'east', 'C-F', 'P-2001', 10, 88000.00, 'confirmed'),
    (2002, '2026-08-04', 'finance', 'east', 'C-G', 'P-2001', 15, 132000.00, 'confirmed'),
    (3001, '2026-08-05', 'sales', 'east', 'C-H', 'P-1001', 18, 16200.00, 'confirmed'),
    (3002, '2026-08-09', 'sales', 'south', 'C-I', 'P-1002', 16, 16800.00, 'confirmed'),
    (3003, '2026-08-13', 'sales', 'north', 'C-J', 'P-1003', 10, 12000.00, 'confirmed'),
    (3004, '2026-08-19', 'sales', 'east', 'C-K', 'P-1001', 28, 25200.00, 'confirmed'),
    (3005, '2026-08-25', 'sales', 'south', 'C-L', 'P-1003', 14, 16800.00, 'confirmed');

INSERT IGNORE INTO inventory_snapshots
    (snapshot_date, department_id, warehouse_id, product_id, quantity_on_hand, quantity_in_transit)
VALUES
    ('2026-08-31', 'sales', 'WH-E', 'P-1001', 320, 80),
    ('2026-08-31', 'sales', 'WH-E', 'P-1002', 180, 0),
    ('2026-08-31', 'sales', 'WH-S', 'P-1003', 95, 40),
    ('2026-08-31', 'finance', 'WH-F', 'P-2001', 45, 10),
    ('2026-08-31', 'operations', 'WH-O', 'P-3001', 600, 120),
    ('2026-08-31', 'supply', 'WH-S', 'P-4001', 210, 60);
