"""应用组合根。

所有具体基础设施适配器都在这里创建，并注入 Skill 和 LangGraph 工作流。
测试可以使用确定性替身替换它们，而无需修改业务逻辑。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import Settings
from app.domain.errors import ConfigurationError
from app.infra.database import Database, PostgresDatabase
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
    """持有一个 FastAPI 进程中的应用级依赖。"""

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
        """创建默认适配器并注入工作流。"""
        self.settings = settings
        self.security = JWTManager(settings)
        self.chat_model = chat_model or OpenAICompatibleChatModel(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            json_mode=settings.llm_json_mode,
        )
        # 注入向量化模型
        self.embedding_provider = embedding_provider or BGEEmbeddingProvider(
            model_name=settings.embedding_model,
            device=settings.embedding_device,
        )
    # 注入向量库
        self.vector_store = vector_store or ChromaVectorStore(
            path=str(settings.chroma_path),
            collection_name=f"knowledge_{settings.embedding_model.replace('/', '_')}_v1",
        )
    # 注入数据库
        self.database = database or PostgresDatabase(
            dsn=settings.postgres_dsn.get_secret_value(),
            default_max_rows=settings.sql_max_rows,
        )
        # 注入文档加载器
        self.document_loader = document_loader or DocumentLoader(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        # 注入数据技能
        self.template_registry = QueryTemplateRegistry(
            timeout_seconds=settings.sql_timeout_seconds,
            max_rows=settings.sql_max_rows,
        )
        # 注入路由技能
        self.router = RouterSkill(
            chat_model=self.chat_model,
            confidence_threshold=settings.router_confidence_threshold,
        )
        # 注入知识技能
        self.knowledge_skill = KnowledgeSkill(
            embedding_provider=self.embedding_provider,
            vector_store=self.vector_store,
            chat_model=self.chat_model,
            top_k=settings.top_k,
            min_score=settings.retrieval_min_score,
        )
        # 注入数据技能
        self.data_skill = DataSkill(
            chat_model=self.chat_model,
            registry=self.template_registry,
            database=self.database,
            confidence_threshold=settings.router_confidence_threshold,
        )
        # 注入工作流
        self.workflow = AgentWorkflow(
            router=self.router,
            knowledge_skill=self.knowledge_skill,
            data_skill=self.data_skill,
        )

    async def startup(self) -> None:
        """执行轻量启动钩子。

        重型 BGE 模型和数据库连接采用延迟创建，使存活检查不依赖外部服务。
        """
        return None

    async def shutdown(self) -> None:
        """释放长期运行的基础设施资源。"""
        await self.database.close()

    async def ingest_demo_documents(self) -> int:
        """对演示文档目录执行向量化并写入向量库。"""
        chunks = self.document_loader.load(self.settings.demo_docs_path)
        if not chunks:
            raise ConfigurationError("演示知识库没有可导入内容")
        embeddings = await self.embedding_provider.embed([chunk.text for chunk in chunks])
        await self.vector_store.upsert(chunks, embeddings)
        return len(chunks)

    async def readiness(self) -> dict[str, bool]:
        """检查完整请求执行所需的外部依赖。"""
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
