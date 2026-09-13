from __future__ import annotations

import os
from datetime import date

import pytest

from app.domain.models import Principal
from app.infra.database import MySQLDatabase
from app.skills.data import QueryTemplateRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MYSQL_TEST_DSN"),
        reason="set MYSQL_TEST_DSN to run the MySQL integration test",
    ),
]


async def test_mysql_template_executes_with_read_only_scope() -> None:
    database = MySQLDatabase(dsn=os.environ["MYSQL_TEST_DSN"])
    template = QueryTemplateRegistry().get("sales_summary")
    assert template is not None
    top_products = QueryTemplateRegistry().get("top_products")
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
            template,
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
