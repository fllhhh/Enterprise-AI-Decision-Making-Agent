"""知识检索管线使用的 Embedding Provider。"""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.domain.errors import ConfigurationError, DependencyUnavailableError


class EmbeddingProvider(Protocol):
    """查询和文档向量化的异步接口。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """为每个输入文本返回一个归一化向量。"""
        ...

    async def health(self) -> bool:
        """返回 Embedding 后端是否可用。"""
        ...


class BGEEmbeddingProvider:
    """延迟加载的本地 BGE Provider。

    模型会延迟到首次 Embedding 请求或健康检查时加载，
    使 API 启动时不必立即下载模型。
    """

    def __init__(self, *, model_name: str, device: str = "cpu") -> None:
        """保存模型配置并延迟执行昂贵的模型加载。"""
        self.model_name = model_name
        self.device = device
        self._model = None
        self._lock = asyncio.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """为一批文本返回归一化向量。"""
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
        """返回模型是否可以加载和推理。"""
        try:
            await self._ensure_model()
            return True
        except Exception:
            return False

    async def _ensure_model(self):
        """在并发访问下只加载一次 SentenceTransformer。"""
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
                # CPU 推理可能阻塞，不能放在事件循环线程中执行模型加载。
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
