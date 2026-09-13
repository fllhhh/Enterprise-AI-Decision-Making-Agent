from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph

try:
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver
except ImportError:  # pragma: no cover - compatibility with older LangGraph
    from langgraph.checkpoint.memory import MemorySaver

from app.domain.models import (
    ErrorDetail,
    Evidence,
    Principal,
    QueryRequest,
    QueryResponse,
    Route,
    RunStatus,
)
from app.graph.state import AgentState
from app.infra.logging import trace_id_var
from app.skills.data import DataSkill
from app.skills.knowledge import KnowledgeSkill
from app.skills.router import RouterSkill

logger = logging.getLogger(__name__)


class AgentWorkflow:
    def __init__(
        self,
        *,
        router: RouterSkill,
        knowledge_skill: KnowledgeSkill,
        data_skill: DataSkill,
    ) -> None:
        self._router = router
        self._knowledge_skill = knowledge_skill
        self._data_skill = data_skill
        self._graph = self._build()

    async def run(self, *, request: QueryRequest, principal: Principal) -> QueryResponse:
        run_id = str(uuid.uuid4())
        thread_id = request.thread_id or str(uuid.uuid4())
        trace_id = trace_id_var.get() or str(uuid.uuid4())
        started = perf_counter()
        initial: AgentState = {
            "query": request.query.strip(),
            "principal": principal.model_dump(),
            "run_id": run_id,
            "trace_id": trace_id,
            "thread_id": thread_id,
        }
        result = await self._graph.ainvoke(
            initial,
            config={"configurable": {"thread_id": thread_id}},
        )
        response = _to_response(result)
        logger.info(
            "agent_run_completed",
            extra={
                "run_id": run_id,
                "thread_id": thread_id,
                "user_id": principal.user_id,
                "route": response.route.value,
                "status": response.status.value,
                "skill": response.route.value,
                "template_id": (result.get("metadata") or {}).get("template_id"),
                "row_count": (result.get("metadata") or {}).get("row_count"),
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return response

    def _build(self):
        graph = StateGraph(AgentState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("route", self._route)
        graph.add_node("knowledge", self._knowledge)
        graph.add_node("data", self._data)
        graph.add_node("clarify", self._clarify)
        graph.add_node("mixed_unsupported", self._mixed_unsupported)
        graph.add_node("validate_evidence", self._validate_evidence)
        graph.add_node("respond", self._respond)

        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "route")
        graph.add_conditional_edges(
            "route",
            _route_branch,
            {
                Route.KNOWLEDGE.value: "knowledge",
                Route.DATA.value: "data",
                Route.CLARIFY.value: "clarify",
                Route.MIXED.value: "mixed_unsupported",
            },
        )
        graph.add_edge("knowledge", "validate_evidence")
        graph.add_edge("data", "validate_evidence")
        graph.add_edge("clarify", "respond")
        graph.add_edge("mixed_unsupported", "respond")
        graph.add_edge("validate_evidence", "respond")
        graph.add_edge("respond", END)
        return graph.compile(checkpointer=MemorySaver())

    async def _prepare(self, state: AgentState) -> dict[str, Any]:
        history = list(state.get("history") or [])
        previous_summary = state.get("conversation_summary") or ""
        if not previous_summary and history:
            previous_summary = _summarize_history(history)
        return {
            "query": state["query"].strip(),
            "conversation_summary": previous_summary,
            "route": Route.CLARIFY.value,
            "route_confidence": 0.0,
            "route_reason": "",
            "status": RunStatus.CLARIFY.value,
            "answer": "",
            "evidence": [],
            "error_code": None,
            "error_message": None,
            "metadata": {},
        }

    async def _route(self, state: AgentState) -> dict[str, Any]:
        decision = await self._router.decide(
            query=state["query"],
            conversation_summary=state.get("conversation_summary", ""),
        )
        return {
            "route": decision.route.value,
            "route_confidence": decision.confidence,
            "route_reason": decision.reason,
        }

    async def _knowledge(self, state: AgentState) -> dict[str, Any]:
        principal = Principal.model_validate(state["principal"])
        outcome = await self._knowledge_skill.answer(
            query=state["query"],
            principal=principal,
        )
        return _outcome_update(outcome)

    async def _data(self, state: AgentState) -> dict[str, Any]:
        principal = Principal.model_validate(state["principal"])
        outcome = await self._data_skill.answer(
            query=state["query"],
            principal=principal,
        )
        return _outcome_update(outcome)

    async def _clarify(self, state: AgentState) -> dict[str, Any]:
        return {
            "status": RunStatus.CLARIFY.value,
            "answer": "请补充要查询的知识主题、数据指标或明确的时间范围。",
            "error_code": "ROUTE_CLARIFY",
        }

    async def _mixed_unsupported(self, state: AgentState) -> dict[str, Any]:
        return {
            "status": RunStatus.UNSUPPORTED.value,
            "answer": "v0.1 暂不支持同时执行知识检索和数据查询，请拆分为两个问题。",
            "error_code": "MIXED_NOT_SUPPORTED",
        }

    async def _validate_evidence(self, state: AgentState) -> dict[str, Any]:
        if state.get("status") != RunStatus.ANSWERED.value:
            return {}
        evidence = state.get("evidence") or []
        if not evidence:
            return {
                "status": RunStatus.CLARIFY.value,
                "answer": "当前没有可验证的证据，无法给出事实性回答。",
                "error_code": "NO_EVIDENCE",
            }

        known_ids = {item["evidence_id"] for item in evidence}
        answer = state.get("answer") or ""
        if state.get("route") == Route.KNOWLEDGE.value and not any(
            f"[{evidence_id}]" in answer for evidence_id in known_ids
        ):
            return {
                "status": RunStatus.CLARIFY.value,
                "answer": "回答未能绑定可验证证据，请换一种问法。",
                "error_code": "EVIDENCE_VALIDATION_FAILED",
            }
        return {}

    async def _respond(self, state: AgentState) -> dict[str, Any]:
        history = list(state.get("history") or [])
        history.append(
            {
                "query": state.get("query", ""),
                "route": state.get("route", Route.CLARIFY.value),
                "status": state.get("status", RunStatus.CLARIFY.value),
                "answer": state.get("answer", ""),
                "evidence_ids": [
                    item.get("evidence_id") for item in state.get("evidence", [])
                ],
            }
        )
        history = history[-5:]
        return {
            "history": history,
            "conversation_summary": _summarize_history(history),
        }


def _route_branch(state: AgentState) -> str:
    return state.get("route", Route.CLARIFY.value)


def _outcome_update(outcome) -> dict[str, Any]:
    return {
        "status": outcome.status.value,
        "answer": outcome.answer,
        "evidence": [item.model_dump(mode="json") for item in outcome.evidence],
        "error_code": outcome.error_code,
        "metadata": outcome.metadata,
    }


def _summarize_history(history: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"用户: {item.get('query', '')}\n助手: {item.get('answer', '')}"
        for item in history[-3:]
    )


def _to_response(state: AgentState) -> QueryResponse:
    route = Route(state.get("route", Route.CLARIFY.value))
    status = RunStatus(state.get("status", RunStatus.CLARIFY.value))
    error_code = state.get("error_code")
    error = None
    if error_code:
        error = ErrorDetail(
            code=error_code,
            message=state.get("answer") or state.get("error_message") or "请求未能完成",
        )
    return QueryResponse(
        run_id=state.get("run_id", str(uuid.uuid4())),
        thread_id=state.get("thread_id", str(uuid.uuid4())),
        trace_id=state.get("trace_id", str(uuid.uuid4())),
        route=route,
        status=status,
        answer=state.get("answer", ""),
        evidence=[
            Evidence.model_validate(item)
            for item in (state.get("evidence") or [])
        ],
        error=error,
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
