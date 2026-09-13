from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    query: str
    principal: dict[str, Any]
    conversation_summary: str
    history: list[dict[str, Any]]
    route: str
    route_confidence: float
    route_reason: str
    status: str
    answer: str
    evidence: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    run_id: str
    trace_id: str
    thread_id: str
    metadata: dict[str, Any]

