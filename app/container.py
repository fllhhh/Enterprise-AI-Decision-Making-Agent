from __future__ import annotations

import asyncio
from typing import Any

from app.config import Settings
from app.domain.errors import ConfigurationError
from app.infra.database import Database, MySQLDatabase
from app.infra.document_loader import DocumentLoader
from app.infra.embeddings import BGEEmbeddingProvider, EmbeddingProvider
from app.infra.llm import ChatModel, OpenAICompatibleChatModel
from app.infra.vector_store import ChromaVectorStore, VectorStore
from app.security.jwt import JWTManager
from app.skills.data import DataSkill, QueryTemplateRegistry
from app.skills.knowledge import KnowledgeSkill
from app.skills.router import RouterSkill
from app.graph.workflow import AgentWorkflow


class AppContainer:
    def __init__(
        self,
        settings: Settings,
        *,
        chat_model: ChatModel | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        database: Database | None = None,
        document_loader: DocumentLoader | None = None,
    ) -> None:
        self.settings = settings
        self.security = JWTManager(settings)
        self.chat_model = chat_model or OpenAICompatibleChatModel(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            json_mode=settings.llm_json_mode,
        )
        self.embedding_provider = embedding_provider or BGEEmbeddingProvider(
            model_name=settings.embedding_model,
            device=settings.embedding_device,
        )
        self.vector_store = vector_store or ChromaVectorStore(
            path=str(settings.chroma_path),
            collection_name=f"knowledge_{settings.embedding_model.replace('/', '_')}_v1",
        )
        self.database = database or MySQLDatabase(
            dsn=settings.mysql_dsn.get_secret_value(),
            default_max_rows=settings.sql_max_rows,
        )
        self.document_loader = document_loader or DocumentLoader(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self.template_registry = QueryTemplateRegistry(
            timeout_seconds=settings.sql_timeout_seconds,
            max_rows=settings.sql_max_rows,
        )
        self.router = RouterSkill(
            chat_model=self.chat_model,
            confidence_threshold=settings.router_confidence_threshold,
        )
        self.knowledge_skill = KnowledgeSkill(
            embedding_provider=self.embedding_provider,
            vector_store=self.vector_store,
            chat_model=self.chat_model,
            top_k=settings.top_k,
            min_score=settings.retrieval_min_score,
        )
        self.data_skill = DataSkill(
            chat_model=self.chat_model,
            registry=self.template_registry,
            database=self.database,
            confidence_threshold=settings.router_confidence_threshold,
        )
        self.workflow = AgentWorkflow(
            router=self.router,
            knowledge_skill=self.knowledge_skill,
            data_skill=self.data_skill,
        )

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        await self.database.close()

    async def ingest_demo_documents(self) -> int:
        chunks = self.document_loader.load(self.settings.demo_docs_path)
        if not chunks:
            raise ConfigurationError("演示知识库没有可导入内容")
        embeddings = await self.embedding_provider.embed([chunk.text for chunk in chunks])
        await self.vector_store.upsert(chunks, embeddings)
        return len(chunks)

    async def readiness(self) -> dict[str, bool]:
        embedding_ok, vector_ok, database_ok = await asyncio.gather(
            self.embedding_provider.health(),
            self.vector_store.health(),
            self.database.health(),
        )
        return {
            "embedding": embedding_ok,
            "vector_store": vector_ok,
            "database": database_ok,
        }
