"""从环境变量和 `.env` 加载的应用配置。

本模块是运行时配置的唯一来源。敏感信息使用 ``SecretStr`` 保存，
避免 Pydantic 在日志或校验错误中输出明文。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """保存 API、模型、存储和安全相关的运行时配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 环境类型会影响生产环境校验和测试依赖装配。
    app_env: Literal["demo", "test", "production"] = "demo"
    log_level: str = "INFO"

    # 对话模型配置。可以使用任何兼容 OpenAI Chat Completions 的接口，
    # 包括本地网关和企业模型服务。
    llm_base_url: str = "http://127.0.0.1:8001/v1"
    llm_api_key: SecretStr = SecretStr("change-me")
    llm_model: str = "qwen-plus"
    llm_timeout_seconds: float = 30.0
    llm_json_mode: bool = True

    # 本地 Embedding 配置。默认 BGE 模型生成归一化向量，
    # 写入持久化 Chroma 集合。
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"

    # 只读 PostgreSQL 数据库。生产环境必须替换演示账号和密码。
    postgres_dsn: SecretStr = SecretStr(
        "postgresql+asyncpg://agent_ro:agent_ro@127.0.0.1:5432/enterpriseAgent"
    )
    app_db_dsn: SecretStr | None = None
    sql_timeout_seconds: float = 3.0
    sql_max_rows: int = Field(default=200, ge=1, le=1000)

    # 本地 JWT 签发者和受众。HS256 仅用于当前开发阶段。
    jwt_secret: SecretStr = SecretStr(
        "replace-with-at-least-32-random-characters"
    )
    jwt_issuer: str = "enterprise-agent-local"
    jwt_audience: str = "enterprise-agent-api"

    # 持久化向量库路径和演示文档来源目录。
    chroma_path: Path = Path("./data/chroma")
    demo_docs_path: Path = Path("./app/resources/demo_docs")

    # 检索和路由质量控制。分数阈值用于阻止无关向量结果进入 Evidence。
    router_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    top_k: int = Field(default=5, ge=1, le=20)
    chunk_size: int = Field(default=600, ge=100, le=3000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    retrieval_min_score: float = Field(default=0.20, ge=0.0, le=1.0)

    # Hybrid RAG 配置。BM25 始终由容器创建，Reranker 默认可选关闭，
    # 使 fake 测试和低资源环境不需要加载第二个模型。
    bm25_k1: float = Field(default=1.5, gt=0.0)
    bm25_b: float = Field(default=0.75, ge=0.0, le=1.0)
    rrf_k: float = Field(default=60.0, gt=0.0)
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_device: str = "cpu"
    query_rewriter_enabled: bool = False

    @field_validator("chunk_overlap")
    @classmethod
    def overlap_must_be_smaller_than_chunk(cls, value: int, info) -> int:
        """拒绝会导致滑动窗口无法前进的分块配置。"""
        chunk_size = info.data.get("chunk_size", 600)
        if value >= chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr, info) -> SecretStr:
        """生产模式下强制使用足够强的 JWT 签名密钥。"""
        if info.data.get("app_env") == "production" and len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return value
