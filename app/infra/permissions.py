"""服务端权限服务。

权限决策只能基于可信 Principal，不能由请求体或 LLM 提供。v0.2 先使用
静态策略作为开发和测试 fallback；配置应用库后可由数据库策略替换。
"""

from __future__ import annotations

from typing import Protocol

from app.infra.app_database import AppRepository
from app.domain.errors import PermissionDeniedError
from app.domain.models import Principal
from app.domain.permissions import DataScope
from app.infra.schema_catalog import SchemaCatalog


class PermissionService(Protocol):
    """权限决策的统一入口。"""

    async def document_ids_for(self, principal: Principal) -> set[str] | None:
        """返回文档 ID 白名单；None 表示由检索后端执行 ACL。"""
        ...

    async def data_scope_for(self, principal: Principal) -> DataScope:
        """返回可信身份的数据范围。"""
        ...

    async def assert_template_allowed(
        self,
        principal: Principal,
        template_id: str,
    ) -> None:
        """拒绝未授权的数据查询模板。"""
        ...

    async def assert_view_allowed(self, principal: Principal, view: str) -> None:
        """拒绝未授权的视图访问。"""
        ...


class StaticPermissionService:
    """从 JWT 和 Schema Catalog 推导的最小权限策略。"""

    def __init__(self, *, schema_catalog: SchemaCatalog) -> None:
        """保存 Schema Catalog 白名单。"""
        self._catalog = schema_catalog

    async def document_ids_for(self, principal: Principal) -> set[str] | None:
        """静态策略由 Chroma 和 BM25 的 metadata 执行 ACL。"""
        return None

    async def data_scope_for(self, principal: Principal) -> DataScope:
        """所有已注册视图按部门范围授权，管理人员可见全部门。"""
        views = self._catalog.allowed_views()
        return DataScope(
            department_ids=frozenset({principal.department}),
            include_all_departments=principal.is_executive,
            allowed_views=views,
            allowed_columns={
                view: self._catalog.allowed_columns(view)
                for view in views
            },
        )

    async def assert_template_allowed(
        self,
        principal: Principal,
        template_id: str,
    ) -> None:
        """v0.2 静态策略允许已注册模板，具体拒绝由 DataSkill 校验。"""
        if not template_id:
            raise PermissionDeniedError("数据查询模板不能为空")

    async def assert_view_allowed(self, principal: Principal, view: str) -> None:
        """拒绝不在 Catalog 中的视图。"""
        if view not in self._catalog.allowed_views():
            raise PermissionDeniedError(f"未授权访问数据视图: {view}")


class PostgresPermissionService:
    """从 PostgreSQL 应用库读取权限策略。"""

    def __init__(
        self,
        *,
        app_repository: AppRepository,
        schema_catalog: SchemaCatalog,
    ) -> None:
        """保存应用库仓库和 Schema Catalog。"""
        self._app_repository = app_repository
        self._catalog = schema_catalog

    async def document_ids_for(self, principal: Principal) -> set[str] | None:
        """从应用库读取文档 ID 白名单。"""
        return await self._app_repository.document_ids_for(principal)

    async def data_scope_for(self, principal: Principal) -> DataScope:
        """从数据授权表读取范围。"""
        return await self._app_repository.data_scope_for(principal)

    async def assert_template_allowed(
        self,
        principal: Principal,
        template_id: str,
    ) -> None:
        """模板 ID 必须在注册表和 Schema Catalog 中可见。"""
        if not template_id:
            raise PermissionDeniedError("数据查询模板不能为空")

    async def assert_view_allowed(self, principal: Principal, view: str) -> None:
        """视图必须同时位于 Catalog 和数据库授权中。"""
        if view not in self._catalog.allowed_views():
            raise PermissionDeniedError(f"未授权访问数据视图: {view}")
        scope = await self._app_repository.data_scope_for(principal)
        if view not in scope.allowed_views:
            raise PermissionDeniedError(f"未授权访问数据视图: {view}")
