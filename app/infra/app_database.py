"""PostgreSQL 应用库仓库，用于权限、会话事件、审计和反馈。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.domain.errors import DependencyUnavailableError
from app.domain.documents import DocumentMetadata
from app.domain.models import Principal
from app.domain.permissions import DataScope


class AppRepository(Protocol):
    """应用数据仓库接口。"""

    async def sync_document_grants(self, metadata: DocumentMetadata) -> None:
        """把文档登记和 ACL 同步到应用库。"""
        ...

    async def document_ids_for(self, principal: Principal) -> set[str]:
        """返回 Principal 有权访问的文档 ID。"""
        ...

    async def data_scope_for(self, principal: Principal) -> DataScope:
        """返回 Principal 的数据范围。"""
        ...

    async def record_thread_event(
        self,
        *,
        thread_id: str,
        run_id: str,
        trace_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """追加会话流事件。"""
        ...

    async def list_thread_events(self, thread_id: str) -> list[dict[str, Any]]:
        """按时间顺序返回会话事件。"""
        ...

    async def record_audit(
        self,
        *,
        trace_id: str,
        run_id: str,
        thread_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """写入审计事件。"""
        ...

    async def list_audits(
        self,
        *,
        trace_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按受控过滤条件返回最近审计记录。"""
        ...

    async def save_feedback(
        self,
        *,
        run_id: str,
        thread_id: str,
        user_id: str,
        rating: int | None,
        comment: str | None,
    ) -> None:
        """保存用户反馈。"""
        ...

    async def health(self) -> bool:
        """返回应用库是否可连接。"""
        ...

    async def close(self) -> None:
        """释放数据库连接。"""
        ...


class PostgresAppRepository:
    """通过 SQLAlchemy Async 访问 PostgreSQL 应用库。"""

    def __init__(self, *, dsn: str) -> None:
        """保存连接串并延迟创建 Engine。"""
        self._dsn = dsn
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def sync_document_grants(self, metadata: DocumentMetadata) -> None:
        """UPSERT 文档并替换其部门、角色和公开授权。"""
        async with self._get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO app.documents
                        (doc_id, title, version, effective_at, source, is_active)
                    VALUES
                        (:doc_id, :title, :version, :effective_at, :source, TRUE)
                    ON CONFLICT (doc_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        version = EXCLUDED.version,
                        effective_at = EXCLUDED.effective_at,
                        source = EXCLUDED.source,
                        is_active = TRUE,
                        updated_at = NOW()
                    """
                ),
                {
                    "doc_id": metadata.doc_id,
                    "title": metadata.title,
                    "version": metadata.version,
                    # asyncpg requires a Python datetime for TIMESTAMPTZ parameters;
                    # DocumentMetadata keeps the catalog value as an ISO string for
                    # Chroma metadata compatibility, so convert it at this boundary.
                    "effective_at": _as_utc(metadata.effective_at),
                    "source": metadata.source,
                },
            )
            await session.execute(
                text("DELETE FROM app.document_grants WHERE doc_id = :doc_id"),
                {"doc_id": metadata.doc_id},
            )
            for grant_type, grant_value in _grant_rows(metadata):
                await session.execute(
                    text(
                        """
                        INSERT INTO app.document_grants
                            (doc_id, grant_type, grant_value, is_active)
                        VALUES
                            (:doc_id, :grant_type, :grant_value, TRUE)
                        """
                    ),
                    {
                        "doc_id": metadata.doc_id,
                        "grant_type": grant_type,
                        "grant_value": grant_value,
                    },
                )
            await session.commit()

    async def list_audits(
        self,
        *,
        trace_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """使用参数绑定查询最近审计记录。"""
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
        for name, value in (("trace_id", trace_id), ("user_id", user_id), ("event_type", event_type)):
            if value:
                conditions.append(f"{name} = :{name}")
                params[name] = value
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = await self._fetch(
            "SELECT trace_id, run_id, thread_id, user_id, event_type, payload, created_at "
            f"FROM app.audit_events{where} ORDER BY created_at DESC LIMIT :limit",
            params,
        )
        return [
            {**row, "payload": _json_loads(row["payload"]), "created_at": _isoformat(row["created_at"])}
            for row in rows
        ]

    async def document_ids_for(self, principal: Principal) -> set[str]:
        """从应用库读取文档授权。"""
        documents = await self._fetch_documents()
        grants = await self._fetch_document_grants()
        now = datetime.now(UTC)
        visible: set[str] = set()
        for doc in documents:
            if not doc.get("is_active"):
                continue
            effective_at = doc.get("effective_at")
            if effective_at is not None:
                effective_at = _as_utc(effective_at)
                if effective_at > now:
                    continue
            doc_id = str(doc["doc_id"])
            if any(
                grant["doc_id"] == doc_id
                and grant.get("is_active")
                and (
                    grant["grant_type"] == "public"
                    or (
                        grant["grant_type"] == "department"
                        and grant["grant_value"] == principal.department
                    )
                    or (
                        grant["grant_type"] == "role"
                        and grant["grant_value"] in principal.roles
                    )
                )
                for grant in grants
            ):
                visible.add(doc_id)
        return visible

    async def data_scope_for(self, principal: Principal) -> DataScope:
        """从数据授权表构建 DataScope。"""
        rows = await self._fetch_data_grants(principal)
        views: set[str] = set()
        columns: dict[str, set[str]] = {}
        departments: set[str] = {principal.department}
        include_all = principal.is_executive
        for row in rows:
            if not row.get("is_active"):
                continue
            view = str(row["view_name"])
            views.add(view)
            columns.setdefault(view, set()).add(str(row["column_name"]))
            if row.get("department_id"):
                departments.add(str(row["department_id"]))
            if bool(row.get("include_all_departments")):
                include_all = True
        return DataScope(
            department_ids=frozenset(departments),
            include_all_departments=include_all,
            allowed_views=frozenset(views),
            allowed_columns={
                view: frozenset(names)
                for view, names in columns.items()
            },
        )

    async def record_thread_event(
        self,
        *,
        thread_id: str,
        run_id: str,
        trace_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """UPSERT 会话头并追加事件。"""
        async with self._get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO app.threads (thread_id, user_id, updated_at)
                    VALUES (:thread_id, :user_id, NOW())
                    ON CONFLICT (thread_id) DO UPDATE
                    SET user_id = EXCLUDED.user_id, updated_at = NOW()
                    """
                ),
                {"thread_id": thread_id, "user_id": user_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO app.thread_events
                        (thread_id, run_id, trace_id, event_type, payload)
                    VALUES
                        (:thread_id, :run_id, :trace_id, :event_type, :payload)
                    """
                ),
                {
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "event_type": event_type,
                    "payload": _json_text(payload),
                },
            )
            await session.commit()

    async def list_thread_events(self, thread_id: str) -> list[dict[str, Any]]:
        """返回会话事件，payload 展开为对象。"""
        async with self._get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT event_type, payload, created_at
                    FROM app.thread_events
                    WHERE thread_id = :thread_id
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"thread_id": thread_id},
            )
        return [
            {
                "event_type": row.event_type,
                "payload": _json_loads(row.payload),
                "created_at": _isoformat(row.created_at),
            }
            for row in result
        ]

    async def record_audit(
        self,
        *,
        trace_id: str,
        run_id: str,
        thread_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """写入不可由普通请求修改的审计记录。"""
        async with self._get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO app.audit_events
                        (trace_id, run_id, thread_id, user_id, event_type, payload)
                    VALUES
                        (:trace_id, :run_id, :thread_id, :user_id, :event_type, :payload)
                    """
                ),
                {
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "payload": _json_text(payload),
                },
            )
            await session.commit()

    async def save_feedback(
        self,
        *,
        run_id: str,
        thread_id: str,
        user_id: str,
        rating: int | None,
        comment: str | None,
    ) -> None:
        """保存 1 到 5 分反馈和可选评论。"""
        async with self._get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO app.feedback
                        (run_id, thread_id, user_id, rating, comment)
                    VALUES
                        (:run_id, :thread_id, :user_id, :rating, :comment)
                    """
                ),
                {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "rating": rating,
                    "comment": comment,
                },
            )
            await session.commit()

    async def health(self) -> bool:
        """执行简单查询确认应用库可用。"""
        try:
            async with self._get_session_factory()() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """销毁 Engine。"""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def _fetch_documents(self) -> list[dict[str, Any]]:
        return await self._fetch(
            "SELECT doc_id, is_active, effective_at FROM app.documents"
        )

    async def _fetch_document_grants(self) -> list[dict[str, Any]]:
        return await self._fetch(
            """
            SELECT doc_id, grant_type, grant_value, is_active
            FROM app.document_grants
            """
        )

    async def _fetch_data_grants(
        self,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        conditions = [
            "(identity_type = 'user' AND identity_value = :user_id)",
            "(identity_type = 'department' AND identity_value = :department)",
        ]
        params: dict[str, Any] = {
            "user_id": principal.user_id,
            "department": principal.department,
        }
        for index, role in enumerate(principal.roles):
            key = f"role_{index}"
            conditions.append(f"(identity_type = 'role' AND identity_value = :{key})")
            params[key] = role
        return await self._fetch(
            f"""
            SELECT view_name, column_name, department_id,
                   include_all_departments, is_active
            FROM app.data_grants
            WHERE is_active = TRUE
              AND ({' OR '.join(conditions)})
            """,
            params,
        )

    async def _fetch(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            async with self._get_session_factory()() as session:
                result = await session.execute(text(query), params or {})
                return [dict(row._mapping) for row in result]
        except Exception as exc:
            raise DependencyUnavailableError("应用数据库暂时不可用") from exc

    def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """延迟创建应用库 Session 工厂。"""
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self._get_engine(),
                expire_on_commit=False,
            )
        return self._session_factory

    def _get_engine(self) -> AsyncEngine:
        """延迟创建应用库 Engine。"""
        if self._engine is None:
            try:
                self._engine = create_async_engine(
                    self._dsn,
                    poolclass=NullPool,
                    pool_pre_ping=True,
                )
            except Exception as exc:
                raise DependencyUnavailableError("无法初始化应用数据库连接") from exc
        return self._engine


class InMemoryAppRepository:
    """测试和本地开发使用的确定性应用库。"""

    def __init__(
        self,
        *,
        document_ids: dict[tuple[str, str], set[str]] | None = None,
        data_scope: DataScope | None = None,
    ) -> None:
        """保存可选授权快照。"""
        self._document_ids = dict(document_ids or {})
        self._data_scope = data_scope
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._audit: list[dict[str, Any]] = []
        self._feedback: list[dict[str, Any]] = []

    async def sync_document_grants(self, metadata: DocumentMetadata) -> None:
        """内存仓库不维护文档授权，直接忽略。"""
        return None

    async def document_ids_for(self, principal: Principal) -> set[str]:
        """返回预配置的文档授权。"""
        return self._document_ids.get(
            (principal.department, ",".join(principal.roles)),
            set(),
        )

    async def data_scope_for(self, principal: Principal) -> DataScope:
        """返回预配置或默认空 DataScope。"""
        if self._data_scope is not None:
            return self._data_scope
        return DataScope(
            department_ids=frozenset({principal.department}),
            include_all_departments=principal.is_executive,
            allowed_views=frozenset(),
            allowed_columns={},
        )

    async def record_thread_event(
        self,
        *,
        thread_id: str,
        run_id: str,
        trace_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """在内存中追加事件。"""
        self._events.setdefault(thread_id, []).append(
            {
                "event_type": event_type,
                "payload": {
                    **payload,
                    "run_id": run_id,
                    "trace_id": trace_id,
                },
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    async def list_thread_events(self, thread_id: str) -> list[dict[str, Any]]:
        """返回内存事件。"""
        return list(self._events.get(thread_id, []))

    async def record_audit(
        self,
        *,
        trace_id: str,
        run_id: str,
        thread_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """在内存中保存审计事件。"""
        self._audit.append(
            {
                "trace_id": trace_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "event_type": event_type,
                "payload": payload,
            }
        )

    async def save_feedback(
        self,
        *,
        run_id: str,
        thread_id: str,
        user_id: str,
        rating: int | None,
        comment: str | None,
    ) -> None:
        """在内存中保存反馈。"""
        self._feedback.append(
            {
                "run_id": run_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "rating": rating,
                "comment": comment,
            }
        )

    async def list_audits(
        self,
        *,
        trace_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = [
            row for row in reversed(self._audit)
            if (not trace_id or row["trace_id"] == trace_id)
            and (not user_id or row["user_id"] == user_id)
            and (not event_type or row["event_type"] == event_type)
        ]
        return rows[: max(1, min(limit, 500))]

    async def health(self) -> bool:
        """内存实现始终可用。"""
        return True

    async def close(self) -> None:
        """提供与真实仓库一致的空关闭钩子。"""
        return None


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _grant_rows(metadata: DocumentMetadata) -> list[tuple[str, str]]:
    """Build database-safe ACL rows for one document."""
    grants: list[tuple[str, str]] = []
    if metadata.acl_public:
        # grant_value participates in the historical composite primary key and
        # is therefore NOT NULL. Public grants use the canonical empty sentinel.
        grants.append(("public", ""))
    grants.extend(("department", value) for value in metadata.acl_departments)
    grants.extend(("role", value) for value in metadata.acl_roles)
    return grants


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return json.loads(value or "{}")


def _as_utc(value: Any) -> datetime:
    """Normalize a datetime or ISO-8601 string to an aware UTC datetime."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(
            "expected a datetime.datetime or ISO-8601 string, "
            f"got {type(value).__name__}"
        )

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _isoformat(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
