"""向量库适配器和支持 ACL 的文档检索。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from app.domain.documents import DocumentChunk, SearchHit, _acl_key
from app.domain.errors import ConfigurationError, DependencyUnavailableError
from app.domain.models import Principal
from app.infra.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)


class VectorStore(Protocol):
    """定义 KnowledgeSkill 使用的存储契约。"""

    async def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> None:
        """存储或替换文档分块及向量。"""
        ...

    async def search(
        self,
        *,
        query: str,
        query_embedding: list[float],
        principal: Principal,
        top_k: int,
    ) -> list[SearchHit]:
        """只返回该 Principal 可见的文档分块。"""
        ...

    async def health(self) -> bool:
        """返回向量后端是否可访问。"""
        ...

    async def count(self) -> int:
        """返回已索引分块数量。"""
        ...


class ChromaVectorStore:
    """使用元数据前置过滤的持久化 Chroma 实现。"""

    def __init__(self, *, path: str, collection_name: str = "knowledge_v1") -> None:
        """保存持久化路径和集合名称。"""
        self._path = path
        self._collection_name = collection_name
        self._client = None
        self._collection = None

    async def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> None:
        """写入分块，并将同一文档的旧版本标记为失效。"""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        collection = self._get_collection()
        for chunk in chunks:
            # 同一 doc_id 可能对应多个分块。写入新版本前，
            # 先将旧分块全部标记为 inactive。
            existing = collection.get(
                where={"doc_id": chunk.metadata.doc_id},
                include=["metadatas"],
            )
            if existing.get("ids"):
                existing_metadata = existing.get("metadatas") or [
                    {} for _ in existing["ids"]
                ]
                collection.update(
                    ids=existing["ids"],
                    metadatas=[
                        {**item, "is_active": False}
                        for item in existing_metadata
                    ],
                )
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[chunk.vector_metadata(is_active=True) for chunk in chunks],
            embeddings=embeddings,
        )

    async def search(
        self,
        *,
        query: str,
        query_embedding: list[float],
        principal: Principal,
        top_k: int,
    ) -> list[SearchHit]:
        """只检索指定 Principal 有权访问的文档。"""
        where = _build_acl_filter(principal)
        if where is None:
            return []
        try:
            result = self._get_collection().query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("vector_search_failed", extra={"error_type": type(exc).__name__})
            raise DependencyUnavailableError("知识库检索暂时不可用") from exc

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        hits: list[SearchHit] = []
        for index, chunk_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 1.0
            hits.append(
                SearchHit(
                    chunk_id=chunk_id,
                    text=documents[index],
                    metadata=dict(metadatas[index]),
                    score=max(0.0, 1.0 - distance),
                )
            )
        return hits

    async def health(self) -> bool:
        """检查本地集合是否可读。"""
        try:
            self._get_collection().count()
            return True
        except Exception:
            return False

    async def count(self) -> int:
        """返回已索引分块数量。"""
        try:
            return int(self._get_collection().count())
        except Exception as exc:
            raise DependencyUnavailableError("知识库暂时不可用") from exc

    def _get_collection(self):
        """首次使用时创建持久化客户端和集合。"""
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError as exc:
            raise ConfigurationError(
                "未安装 Chroma 依赖，请执行 pip install -e '.[rag]'"
            ) from exc
        self._client = chromadb.PersistentClient(
            path=self._path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection


def _build_acl_filter(principal: Principal, now: datetime | None = None) -> dict[str, Any] | None:
    """在向量相似度检索前构建 Chroma ``where`` 表达式。

    先执行元数据过滤，避免先召回未授权片段、再在结果中补救过滤。
    """
    effective_now = (now or datetime.now(UTC)).timestamp()
    acl_alternatives: list[dict[str, Any]] = [{"acl_public": {"$eq": True}}]
    acl_alternatives.append(
        {_acl_key("department", principal.department): {"$eq": True}}
    )
    for role in principal.roles:
        acl_alternatives.append({_acl_key("role", role): {"$eq": True}})

    clauses: list[dict[str, Any]] = [
        {"is_active": {"$eq": True}},
        {"effective_ts": {"$lte": effective_now}},
    ]
    if len(acl_alternatives) == 1:
        return None
    clauses.append({"$or": acl_alternatives})
    return {"$and": clauses}
