from __future__ import annotations

import asyncio
from typing import Protocol

from app.domain.errors import ConfigurationError, DependencyUnavailableError


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def health(self) -> bool: ...


class BGEEmbeddingProvider:
    def __init__(self, *, model_name: str, device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model = None
        self._lock = asyncio.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._ensure_model()
        try:
            vectors = await asyncio.to_thread(
                model.encode,
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise DependencyUnavailableError("Embedding 推理失败") from exc
        return [list(map(float, vector)) for vector in vectors]

    async def health(self) -> bool:
        try:
            await self._ensure_model()
            return True
        except Exception:
            return False

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ConfigurationError(
                    "未安装 RAG 依赖，请执行 pip install -e '.[rag]'"
                ) from exc
            try:
                self._model = await asyncio.to_thread(
                    SentenceTransformer,
                    self.model_name,
                    device=self.device,
                )
            except Exception as exc:
                raise DependencyUnavailableError(
                    f"无法加载 Embedding 模型 {self.model_name}"
                ) from exc
            return self._model

