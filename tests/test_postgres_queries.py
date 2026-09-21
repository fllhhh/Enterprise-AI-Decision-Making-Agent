"""不依赖真实数据库的 PostgreSQL ORM 查询编译测试。"""

from __future__ import annotations

from datetime import date

from sqlalchemy.dialects import postgresql

from app.skills.data import QueryTemplateRegistry


def test_all_templates_compile_for_postgresql() -> None:
    """确保所有模板都能编译为 PostgreSQL SQL。"""
    registry = QueryTemplateRegistry()
    parameters = {
        "department_id": "sales",
        "include_all_departments": 0,
        "row_limit": 200,
        "period_start": date(2026, 7, 1),
        "period_end": date(2026, 8, 31),
        "top_n": 5,
    }

    for template in registry.all():
        statement = template.statement_builder(parameters)
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "v_ai_" in sql
        assert "LIMIT" in sql


def test_sales_summary_uses_postgresql_date_format() -> None:
    """销售汇总应使用 PostgreSQL 的 ``to_char`` 月份格式。"""
    template = QueryTemplateRegistry().get("sales_summary")
    assert template is not None
    statement = template.statement_builder(
        {
            "department_id": "sales",
            "include_all_departments": 0,
            "row_limit": 200,
            "period_start": date(2026, 7, 1),
            "period_end": date(2026, 7, 31),
        }
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "to_char" in sql
    assert "DATE_FORMAT" not in sql

