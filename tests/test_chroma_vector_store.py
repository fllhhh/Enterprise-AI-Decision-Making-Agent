from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.models import Principal
from app.infra.document_loader import DocumentLoader
from app.infra.fakes import FakeEmbeddingProvider

pytest.importorskip("chromadb")

from app.infra.vector_store import ChromaVectorStore


async def test_chroma_applies_acl_before_search(tmp_path: Path) -> None:
    chunks = DocumentLoader().load(Path("app/resources/demo_docs"))
    embeddings = FakeEmbeddingProvider()
    vectors = await embeddings.embed([chunk.text for chunk in chunks])
    store = ChromaVectorStore(path=str(tmp_path / "chroma"))
    await store.upsert(chunks, vectors)

    sales_user = Principal(
        user_id="u-sales",
        department="sales",
        roles=("employee",),
        issuer="enterprise-agent-local",
        audience="enterprise-agent-api",
    )
    query_vector = (
        await embeddings.embed(["员工差旅住宿标准是什么？"])
    )[0]
    hits = await store.search(
        query="员工差旅住宿标准是什么？",
        query_embedding=query_vector,
        principal=sales_user,
        top_k=10,
    )
    assert all(hit.metadata["doc_id"] != "doc-travel-policy" for hit in hits)


async def test_chroma_stores_version_and_effective_timestamp(tmp_path: Path) -> None:
    chunks = DocumentLoader().load(Path("app/resources/demo_docs"))
    embeddings = FakeEmbeddingProvider()
    vectors = await embeddings.embed([chunk.text for chunk in chunks])
    store = ChromaVectorStore(path=str(tmp_path / "chroma-meta"))
    await store.upsert(chunks, vectors)

    assert await store.health()
    assert await store.count() == len(chunks)

