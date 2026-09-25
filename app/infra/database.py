"""用于执行已审核 ORM 查询模板的只读 PostgreSQL 适配器。"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.domain.errors import (
    DependencyUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
)
from app.domain.models import Principal
from app.domain.query_templates import QueryTemplate
from app.infra.schema_catalog import SchemaCatalog
from app.infra.sql_guard import SqlGuard, SqlPolicy

logger = logging.getLogger(__name__)


class Database(Protocol):
    """定义 DataSkill 和测试替身共用的数据访问契约。"""

    async def execute_template(
        self,
        template: QueryTemplate,
        arguments: dict[str, Any],
        principal: Principal,
    ) -> list[dict[str, Any]]:
        """执行一个已审核模板并返回 JSON 安全结果。"""
        ...

    async def health(self) -> bool:
        """返回底层数据库是否可连接。"""
        ...

    async def close(self) -> None:
        """释放数据库资源。"""
        ...


class PostgresDatabase:
    """通过 SQLAlchemy ORM 和 asyncpg 执行白名单查询模板。"""

    def __init__(
        self,
        *,
        dsn: str,
        default_max_rows: int = 200,
        schema_catalog: SchemaCatalog | None = None,
        sql_guard: SqlGuard | None = None,
    ) -> None:
        """保存连接配置并延迟创建 Engine。"""
        self._dsn = dsn
        self._default_max_rows = default_max_rows
        self._schema_catalog = schema_catalog or SchemaCatalog()
        self._sql_guard = sql_guard or SqlGuard()
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def execute_template(
        self,
        template: QueryTemplate,
        arguments: dict[str, Any],
        principal: Principal,
    ) -> list[dict[str, Any]]:
        """绑定已校验参数并执行一个已注册 ORM 查询。"""
        parameters = {
            **arguments,
            "department_id": principal.department,
            "include_all_departments": 1 if principal.is_executive else 0,
            "row_limit": template.max_rows or self._default_max_rows,
        }
        try:
            async with asyncio.timeout(template.timeout_seconds):
                statement = template.statement_builder(parameters)
                if self._schema_catalog is not None:
                    compiled = statement.compile(
                        dialect=postgresql.dialect(),
                        compile_kwargs={"literal_binds": True},
                    )
                    self._sql_guard.validate(
                        str(compiled),
                        policy=SqlPolicy.from_catalog(
                            self._schema_catalog,
                            max_rows=template.max_rows or self._default_max_rows,
                        ),
                    )
                async with self._get_session_factory()() as session:
                    result = await session.execute(statement)
                    rows = result.mappings().fetchmany(template.max_rows)
        except TimeoutError as exc:
            raise QueryTimeoutError("数据查询超过执行时限") from exc
        except Exception as exc:
            logger.warning("sql_execution_failed", extra={"template_id": template.template_id})
            raise QueryExecutionError("数据查询执行失败") from exc
        return [{key: _json_safe(value) for key, value in row.items()} for row in rows]

    async def health(self) -> bool:
        """执行简单查询以验证数据库连接。"""
        try:
            async with self._get_session_factory()() as session:
                await session.execute(select(1))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """销毁 Engine 并释放连接。"""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """延迟创建 PostgreSQL 异步 Session 工厂。"""
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self._get_engine(),
                expire_on_commit=False,
            )
        return self._session_factory

    def _get_engine(self) -> AsyncEngine:
        """使用只读 DSN 延迟创建异步 Engine。"""
        if self._engine is None:
            try:
                self._engine = create_async_engine(
                    self._dsn,
                    poolclass=NullPool,
                    pool_pre_ping=True,
                )
            except Exception as exc:
                raise DependencyUnavailableError("无法初始化 PostgreSQL 连接") from exc
        return self._engine


def _json_safe(value: Any) -> Any:
    """将数据库标量值转换为可 JSON 序列化的 Python 值。"""
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
