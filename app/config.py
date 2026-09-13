from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["demo", "test", "production"] = "demo"
    log_level: str = "INFO"

    llm_base_url: str = "http://127.0.0.1:8001/v1"
    llm_api_key: SecretStr = SecretStr("change-me")
    llm_model: str = "qwen-plus"
    llm_timeout_seconds: float = 30.0
    llm_json_mode: bool = True

    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"

    mysql_dsn: SecretStr = SecretStr(
        "mysql+asyncmy://agent_ro:agent_ro@127.0.0.1:3306/"
        "enterprise_demo?charset=utf8mb4"
    )
    sql_timeout_seconds: float = 3.0
    sql_max_rows: int = Field(default=200, ge=1, le=1000)

    jwt_secret: SecretStr = SecretStr(
        "replace-with-at-least-32-random-characters"
    )
    jwt_issuer: str = "enterprise-agent-local"
    jwt_audience: str = "enterprise-agent-api"

    chroma_path: Path = Path("./data/chroma")
    demo_docs_path: Path = Path("./app/resources/demo_docs")

    router_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    top_k: int = Field(default=5, ge=1, le=20)
    chunk_size: int = Field(default=600, ge=100, le=3000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    retrieval_min_score: float = Field(default=0.20, ge=0.0, le=1.0)

    @field_validator("chunk_overlap")
    @classmethod
    def overlap_must_be_smaller_than_chunk(cls, value: int, info) -> int:
        chunk_size = info.data.get("chunk_size", 600)
        if value >= chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr, info) -> SecretStr:
        if info.data.get("app_env") == "production" and len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return value
