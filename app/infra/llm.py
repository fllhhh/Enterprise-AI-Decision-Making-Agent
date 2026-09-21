"""用于路由、模板选择和基于证据回答的对话模型适配器。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

import httpx

from app.domain.errors import DependencyUnavailableError

logger = logging.getLogger(__name__)


class ChatModel(Protocol):
    """应用所需的最小异步对话接口。"""

    async def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> str:
        """根据 Prompt 生成普通文本。"""
        ...

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """根据 Prompt 生成 JSON 对象。"""
        ...


class OpenAICompatibleChatModel:
    """用于调用 OpenAI 兼容 ``/chat/completions`` 接口。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        json_mode: bool = True,
    ) -> None:
        """保存地址、凭据、模型和超时配置。"""
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = httpx.Timeout(timeout_seconds)
        self._json_mode = json_mode

    async def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> str:
        """返回用于答案生成的普通文本。"""
        return await self._request(prompt, system_prompt=system_prompt, json_mode=False)

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """请求 JSON 并解析为字典。"""
        content = await self._request(prompt, system_prompt=system_prompt, json_mode=self._json_mode)
        return _extract_json(content)

    async def _request(
        self,
        prompt: str,
        *,
        system_prompt: str | None,
        json_mode: bool,
    ) -> str:
        """发送一次 Chat Completion 请求并返回首条消息内容。"""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if response.status_code == 400 and json_mode:
                    # 部分兼容网关支持通过 Prompt 返回 JSON，但拒绝 response_format，
                    # 因此去掉该参数后重试一次。
                    payload.pop("response_format", None)
                    response = await client.post(
                        self._endpoint,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("llm_request_failed", extra={"error_type": type(exc).__name__})
            raise DependencyUnavailableError("模型服务暂时不可用") from exc

        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DependencyUnavailableError("模型服务返回格式无效") from exc


def _extract_json(content: str) -> dict[str, Any]:
    """从原始内容或 Markdown 代码块中提取 JSON 对象。"""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise DependencyUnavailableError("模型未返回有效 JSON") from exc
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as nested_exc:
            raise DependencyUnavailableError("模型未返回有效 JSON") from nested_exc
    if not isinstance(value, dict):
        raise DependencyUnavailableError("模型 JSON 响应的顶层必须是对象")
    return value
