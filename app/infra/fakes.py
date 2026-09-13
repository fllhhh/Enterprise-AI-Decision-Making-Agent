from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime
from typing import Any

from app.domain.documents import DocumentChunk, SearchHit, _acl_key
from app.domain.models import Principal
from app.domain.query_templates import QueryTemplate


class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    async def health(self) -> bool:
        return True

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _tokens(text)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._records: dict[str, tuple[str, dict[str, Any]]] = {}

    async def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> None:
        doc_ids = {chunk.metadata.doc_id for chunk in chunks}
        for chunk_id, (text, metadata) in list(self._records.items()):
            if metadata.get("doc_id") in doc_ids:
                self._records[chunk_id] = (text, {**metadata, "is_active": False})
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            metadata = chunk.vector_metadata(is_active=True)
            metadata["_embedding"] = embedding
            self._records[chunk.chunk_id] = (chunk.text, metadata)

    async def search(
        self,
        *,
        query: str,
        query_embedding: list[float],
        principal: Principal,
        top_k: int,
    ) -> list[SearchHit]:
        now = datetime.now(UTC).timestamp()
        hits: list[SearchHit] = []
        for chunk_id, (text, metadata) in self._records.items():
            if not _is_visible(metadata, principal, now):
                continue
            embedding = metadata.get("_embedding", [])
            vector_score = sum(
                left * right for left, right in zip(query_embedding, embedding, strict=False)
            )
            score = max(vector_score, _lexical_similarity(query, text) * 2.0)
            hits.append(
                SearchHit(
                    chunk_id=chunk_id,
                    text=text,
                    metadata={
                        key: value
                        for key, value in metadata.items()
                        if key != "_embedding"
                    },
                    score=float(score),
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]

    async def health(self) -> bool:
        return True

    async def count(self) -> int:
        return len(self._records)


class FakeDatabase:
    async def execute_template(
        self,
        template: QueryTemplate,
        arguments: dict[str, Any],
        principal: Principal,
    ) -> list[dict[str, Any]]:
        if template.template_id == "sales_summary":
            return [
                {"period": "2026-07", "total_amount": 128000.0, "order_count": 32},
                {"period": "2026-08", "total_amount": 156500.0, "order_count": 41},
            ]
        if template.template_id == "top_products":
            return [
                {
                    "product_id": "P-1001",
                    "total_quantity": 120,
                    "total_amount": 98000.0,
                },
                {
                    "product_id": "P-1002",
                    "total_quantity": 90,
                    "total_amount": 76000.0,
                },
            ][: int(arguments.get("top_n", 5))]
        if template.template_id == "inventory_balance":
            return [
                {
                    "product_id": "P-1001",
                    "quantity_on_hand": 320,
                    "quantity_in_transit": 80,
                },
                {
                    "product_id": "P-1002",
                    "quantity_on_hand": 180,
                    "quantity_in_transit": 0,
                },
            ]
        return []

    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class FakeChatModel:
    def __init__(
        self,
        *,
        text_responses: list[str] | None = None,
        json_responses: list[dict[str, Any]] | None = None,
    ) -> None:
        self.text_responses = list(text_responses or [])
        self.json_responses = list(json_responses or [])

    async def generate_text(self, prompt: str, *, system_prompt: str | None = None) -> str:
        if self.text_responses:
            return self.text_responses.pop(0)
        return "根据当前可用企业资料，问题已有对应依据 [E1]。"

    async def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        if self.json_responses:
            return self.json_responses.pop(0)
        return _fake_json_for_prompt(prompt)


def _fake_json_for_prompt(prompt: str) -> dict[str, Any]:
    if "分类为以下 route" in prompt:
        query = _prompt_tail(prompt, "用户问题：")
        route = _fake_route(query)
        return {"route": route, "confidence": 0.82, "reason": "fake classifier"}
    if "白名单模板" in prompt:
        query = _prompt_tail(prompt, "用户问题：")
        return _fake_template_decision(query)
    return {}


def _fake_route(query: str) -> str:
    knowledge = any(
        term in query
        for term in (
            "制度",
            "政策",
            "流程",
            "规定",
            "手册",
            "如何",
            "怎么",
            "要求",
            "口径",
            "定义",
            "含义",
            "意思",
            "规则",
            "标准",
            "排序",
            "计算",
            "哪个",
            "哪些",
            "什么",
            "是否",
            "多久",
            "期限",
            "时限",
            "什么时候",
        )
    )
    data = any(
        term in query
        for term in (
            "销售",
            "库存",
            "订单",
            "金额",
            "统计",
            "排名",
            "多少",
            "结余",
            "畅销",
            "top",
            "TOP",
        )
    )
    if knowledge and data and any(term in query for term in ("结合", "同时", "综合分析")):
        return "mixed"
    if knowledge and data and any(
        term in query
        for term in (
            "制度",
            "政策",
            "流程",
            "规定",
            "手册",
            "口径",
            "定义",
            "含义",
            "意思",
            "规则",
            "标准",
            "如何",
            "怎么",
        )
    ):
        return "knowledge"
    if knowledge:
        return "knowledge"
    if data:
        return "data"
    return "clarify"


def _fake_template_decision(query: str) -> dict[str, Any]:
    if any(term in query for term in ("库存", "在库", "在途", "结余")):
        return {
            "template_id": "inventory_balance",
            "arguments": {},
            "confidence": 0.90,
            "reason": "库存查询",
        }
    template_id = "top_products" if any(
        term in query for term in ("畅销", "排名", "最高", "top", "TOP")
    ) else "sales_summary"
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", query)
    if len(dates) < 2:
        period = re.search(r"(20\d{2})年(\d{1,2})月", query)
        if period:
            year = int(period.group(1))
            month = int(period.group(2))
            start = date(year, month, 1)
            next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            end = date.fromordinal(next_month.toordinal() - 1)
            dates = [start.isoformat(), end.isoformat()]
    if len(dates) < 2:
        return {
            "template_id": template_id,
            "arguments": {},
            "confidence": 0.40,
            "reason": "缺少日期范围",
        }
    arguments: dict[str, Any] = {
        "period_start": dates[0],
        "period_end": dates[1],
    }
    top_match = re.search(r"(?:前|top)\s*(\d+)", query, flags=re.IGNORECASE)
    if top_match:
        arguments["top_n"] = int(top_match.group(1))
    return {
        "template_id": template_id,
        "arguments": arguments,
        "confidence": 0.90,
        "reason": "模板参数已提取",
    }


def _prompt_tail(prompt: str, marker: str) -> str:
    return prompt.rsplit(marker, maxsplit=1)[-1].strip()


def _tokens(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", text)
    tokens = list(compact)
    tokens.extend(compact[index : index + 2] for index in range(max(0, len(compact) - 1)))
    return tokens


def _lexical_similarity(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens.intersection(right_tokens)) / math.sqrt(
        len(left_tokens) * len(right_tokens)
    )


def _is_visible(metadata: dict[str, Any], principal: Principal, now: float) -> bool:
    if not metadata.get("is_active"):
        return False
    if float(metadata.get("effective_ts", 0.0)) > now:
        return False
    if metadata.get("acl_public"):
        return True
    if metadata.get(_acl_key("department", principal.department)):
        return True
    return any(metadata.get(_acl_key("role", role)) for role in principal.roles)
