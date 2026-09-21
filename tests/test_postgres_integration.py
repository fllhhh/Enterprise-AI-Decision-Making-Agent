"""PostgreSQL ORM 查询集成测试。"""

from __future__ import annotations

import os
from datetime import date

import pytest

from app.domain.models import Principal
from app.infra.database import PostgresDatabase
from app.skills.data import QueryTemplateRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("POSTGRES_TEST_DSN"),
        reason="set POSTGRES_TEST_DSN to run the PostgreSQL integration test",
    ),
]


async def test_postgres_template_executes_with_read_only_scope() -> None:
    """使用只读账号执行 ORM 模板并验证返回字段。"""
    database = PostgresDatabase(dsn=os.environ["POSTGRES_TEST_DSN"])
    registry = QueryTemplateRegistry()
    sales_summary = registry.get("sales_summary")
    top_products = registry.get("top_products")
    assert sales_summary is not None
    assert top_products is not None

    principal = Principal(
        user_id="u-sales",
        department="sales",
        roles=("employee",),
        issuer="enterprise-agent-local",
        audience="enterprise-agent-api",
    )
    try:
        sales_rows = await database.execute_template(
            sales_summary,
            {
                "period_start": date(2026, 7, 1),
                "period_end": date(2026, 8, 31),
            },
            principal,
        )
        product_rows = await database.execute_template(
            top_products,
            {
                "period_start": date(2026, 7, 1),
                "period_end": date(2026, 8, 31),
                "top_n": 5,
            },
            principal,
        )
    finally:
        await database.close()

    assert sales_rows
    assert all(row["total_amount"] >= 0 for row in sales_rows)
    assert product_rows
    assert all(str(row["product_id"]).startswith("P-1") for row in product_rows)

