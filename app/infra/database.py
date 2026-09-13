from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.errors import (
    DependencyUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
)
from app.domain.models import Principal
from app.domain.query_templates import QueryTemplate

logger = logging.getLogger(__name__)


class Database(Protocol):
    async def execute_template(
        self,
        template: QueryTemplate,
        arguments: dict[str, Any],
        principal: Principal,
    ) -> list[dict[str, Any]]: ...

    async def health(self) -> bool: ...

    async def close(self) -> None: ...


class MySQLDatabase:
    def __init__(self, *, dsn: str, default_max_rows: int = 200) -> None:
        self._dsn = dsn
        self._default_max_rows = default_max_rows
        self._engine: AsyncEngine | None = None

    async def execute_template(
        self,
        template: QueryTemplate,
        arguments: dict[str, Any],
        principal: Principal,
    ) -> list[dict[str, Any]]:
        parameters = {
            **arguments,
            "department_id": principal.department,
            "include_all_departments": 1 if principal.is_executive else 0,
            "row_limit": template.max_rows or self._default_max_rows,
        }
        try:
            async with asyncio.timeout(template.timeout_seconds):
                async with self._get_engine().connect() as connection:
                    result = await connection.execute(text(template.sql), parameters)
                    rows = result.mappings().fetchmany(template.max_rows)
        except TimeoutError as exc:
            raise QueryTimeoutError("数据查询超过执行时限") from exc
        except Exception as exc:
            logger.warning("sql_execution_failed", extra={"template_id": template.template_id})
            raise QueryExecutionError("数据查询执行失败") from exc
        return [{key: _json_safe(value) for key, value in row.items()} for row in rows]

    async def health(self) -> bool:
        try:
            async with self._get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    def _get_engine(self) -> AsyncEngine:
        if self._engine is None:
            try:
                self._engine = create_async_engine(
                    self._dsn,
                    poolclass=NullPool,
                    pool_pre_ping=True,
                )
            except Exception as exc:
                raise DependencyUnavailableError("无法初始化数据库连接") from exc
        return self._engine


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

