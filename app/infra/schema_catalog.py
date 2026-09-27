"""受控数据查询使用的 Schema Catalog 和指标字典。

这里只声明 Agent 可以访问的只读视图、列和可复算指标。LLM 不会收到
任意表结构，只会在受控 Prompt 中看到必要的能力描述。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchemaTable:
    """一个通过 SQLGlot 白名单校验的只读视图。"""

    name: str
    columns: frozenset[str]


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """服务端维护的业务指标定义。"""

    metric_id: str
    title: str
    description: str
    view: str
    expression: str
    arguments: tuple[str, ...] = ()


DEFAULT_SCHEMA_TABLES = (
    SchemaTable(
        name="v_ai_sales_orders",
        columns=frozenset(
            {
                "order_id",
                "order_date",
                "department_id",
                "region",
                "customer_id",
                "product_id",
                "quantity",
                "amount",
            }
        ),
    ),
    SchemaTable(
        name="v_ai_inventory_snapshots",
        columns=frozenset(
            {
                "snapshot_date",
                "department_id",
                "warehouse_id",
                "product_id",
                "quantity_on_hand",
                "quantity_in_transit",
            }
        ),
    ),
)

DEFAULT_METRICS = (
    MetricDefinition(
        metric_id="sales_summary",
        title="销售汇总",
        description="按月份汇总指定日期范围内的销售额和订单量",
        view="v_ai_sales_orders",
        expression=(
            "SELECT TO_CHAR(order_date, 'YYYY-MM') AS period, "
            "SUM(amount) AS total_amount, COUNT(order_id) AS order_count "
            "FROM v_ai_sales_orders"
        ),
        arguments=("period_start", "period_end"),
    ),
    MetricDefinition(
        metric_id="top_products",
        title="畅销商品",
        description="按日期范围统计销售额最高的商品",
        view="v_ai_sales_orders",
        expression=(
            "SELECT product_id, SUM(quantity) AS total_quantity, "
            "SUM(amount) AS total_amount FROM v_ai_sales_orders"
        ),
        arguments=("period_start", "period_end", "top_n"),
    ),
    MetricDefinition(
        metric_id="inventory_balance",
        title="库存结余",
        description="查询当前商品的在库数量和在途数量",
        view="v_ai_inventory_snapshots",
        expression=(
            "SELECT product_id, SUM(quantity_on_hand) AS quantity_on_hand, "
            "SUM(quantity_in_transit) AS quantity_in_transit "
            "FROM v_ai_inventory_snapshots"
        ),
        arguments=(),
    ),
    MetricDefinition(
        metric_id="inventory_velocity",
        title="商品历史销量",
        description="按日期范围汇总商品销量，供库存风险诊断使用",
        view="v_ai_sales_orders",
        expression="SELECT product_id, SUM(quantity) AS total_quantity FROM v_ai_sales_orders",
        arguments=("period_start", "period_end"),
    ),
)


class SchemaCatalog:
    """从内存声明中提供只读表和列白名单。"""

    def __init__(
        self,
        *,
        tables: tuple[SchemaTable, ...] = DEFAULT_SCHEMA_TABLES,
    ) -> None:
        """保存表和列的只读契约。"""
        self._tables = {table.name: table for table in tables}

    def table(self, name: str) -> SchemaTable | None:
        """返回已注册表，未注册时返回 None。"""
        return self._tables.get(name)

    def allowed_views(self) -> frozenset[str]:
        """返回全部允许查询的视图名。"""
        return frozenset(self._tables)

    def allowed_columns(self, view: str) -> frozenset[str]:
        """返回指定视图允许查询的列。"""
        table = self._tables.get(view)
        return table.columns if table else frozenset()
