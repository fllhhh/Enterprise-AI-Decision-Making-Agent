from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

import httpx

from app.domain.errors import DependencyUnavailableError

logger = logging.getLogger(__name__)


class ChatModel(Protocol):
    async def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> str: ...

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]: ...


class OpenAICompatibleChatModel:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        json_mode: bool = True,
    ) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = httpx.Timeout(timeout_seconds)
        self._json_mode = json_mode

    async def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> str:
        return await self._request(prompt, system_prompt=system_prompt, json_mode=False)

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        content = await self._request(prompt, system_prompt=system_prompt, json_mode=self._json_mode)
        return _extract_json(content)

    async def _request(
        self,
        prompt: str,
        *,
        system_prompt: str | None,
        json_mode: bool,
    ) -> str:
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

