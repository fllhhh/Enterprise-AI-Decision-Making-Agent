"""协调路由、Skill 和 Evidence 校验的 LangGraph 工作流。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from time import perf_counter
from collections.abc import AsyncIterator
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
    """让一次请求通过固定的可信决策工作流图。"""

    def __init__(
        self,
        *,
        router: RouterSkill,
        knowledge_skill: KnowledgeSkill,
        data_skill: DataSkill,
    ) -> None:
        """保存 Skill 依赖，并只编译一次固定工作流图。"""
        self._router = router
        self._knowledge_skill = knowledge_skill
        self._data_skill = data_skill
        self._graph = self._build()

    async def run(self, *, request: QueryRequest, principal: Principal) -> QueryResponse:
        """执行工作流，并将最终状态转换为 API 响应。"""
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

    async def stream(
        self,
        *,
        request: QueryRequest,
        principal: Principal,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式执行工作流，产出前端可消费的事件对象。"""
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
        yield _event(
            "run_started",
            run_id,
            trace_id,
            thread_id,
            {"query": request.query.strip(), "user_id": principal.user_id},
        )
        config = {"configurable": {"thread_id": thread_id}}
        try:
            async for update in self._graph.astream(
                initial,
                config=config,
                stream_mode="updates",
            ):
                for node_name, patch in update.items():
                    if node_name == "knowledge":
                        yield _event(
                            "retrieval_started",
                            run_id,
                            trace_id,
                            thread_id,
                            {},
                        )
                    for event_type, payload in _events_for_node(node_name, patch):
                        yield _event(
                            event_type,
                            run_id,
                            trace_id,
                            thread_id,
                            payload,
                        )
                    if node_name == "knowledge":
                        yield _event(
                            "retrieval_completed",
                            run_id,
                            trace_id,
                            thread_id,
                            {"hit_count": (patch.get("metadata") or {}).get("hit_count", 0)},
                        )

            final_state = await self._graph.aget_state(config)
            response = _to_response(final_state.values)
            yield _event(
                "completed",
                run_id,
                trace_id,
                thread_id,
                response.model_dump(mode="json"),
            )
            logger.info(
                "agent_stream_completed",
                extra={
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "user_id": principal.user_id,
                    "route": response.route.value,
                    "status": response.status.value,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
        except Exception as exc:
            logger.exception(
                "agent_stream_failed",
                extra={"run_id": run_id, "error_type": type(exc).__name__},
            )
            yield _event(
                "error",
                run_id,
                trace_id,
                thread_id,
                {"code": "INTERNAL_ERROR", "message": "服务内部错误"},
            )

    def _build(self):
        """创建并编译固定工作流拓扑。"""
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
        """重置每轮字段，同时保留会话上下文。"""
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
        """执行 Router，并将决策写入 Graph 状态。"""
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
        """执行文档检索和基于证据回答分支。"""
        principal = Principal.model_validate(state["principal"])
        outcome = await self._knowledge_skill.answer(
            query=state["query"],
            principal=principal,
        )
        return _outcome_update(outcome)

    async def _data(self, state: AgentState) -> dict[str, Any]:
        """执行白名单数据查询分支。"""
        principal = Principal.model_validate(state["principal"])
        outcome = await self._data_skill.answer(
            query=state["query"],
            principal=principal,
        )
        return _outcome_update(outcome)

    async def _clarify(self, state: AgentState) -> dict[str, Any]:
        """当路由不明确时，要求用户补充信息。"""
        return {
            "status": RunStatus.CLARIFY.value,
            "answer": "请补充要查询的知识主题、数据指标或明确的时间范围。",
            "error_code": "ROUTE_CLARIFY",
        }

    async def _mixed_unsupported(self, state: AgentState) -> dict[str, Any]:
        """明确拒绝超出当前版本范围的 Mixed 请求。"""
        return {
            "status": RunStatus.UNSUPPORTED.value,
            "answer": "当前版本暂不支持同时执行知识检索和数据查询，请拆分为两个问题。",
            "error_code": "MIXED_NOT_SUPPORTED",
        }

    async def _validate_evidence(self, state: AgentState) -> dict[str, Any]:
        """在响应前执行确定性的最低 Evidence 门禁。"""
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
        """保存精简会话摘要并准备最终状态。"""
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
    """返回 Router 选择的条件下一步节点。"""
    return state.get("route", Route.CLARIFY.value)


def _outcome_update(outcome) -> dict[str, Any]:
    """将 Skill 执行结果转换为 LangGraph 状态补丁。"""
    return {
        "status": outcome.status.value,
        "answer": outcome.answer,
        "evidence": [item.model_dump(mode="json") for item in outcome.evidence],
        "error_code": outcome.error_code,
        "metadata": outcome.metadata,
    }


def _event(
    event_type: str,
    run_id: str,
    trace_id: str,
    thread_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """构造统一的 SSE 事件对象。"""
    return {
        "event": event_type,
        "run_id": run_id,
        "trace_id": trace_id,
        "thread_id": thread_id,
        "payload": payload,
    }


def _events_for_node(
    node_name: str,
    patch: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """把节点状态补丁映射为流式事件。"""
    if not isinstance(patch, dict):
        return []
    if node_name == "route":
        return [
            (
                "route",
                {
                    "route": patch.get("route"),
                    "confidence": patch.get("route_confidence"),
                    "reason": patch.get("route_reason"),
                },
            )
        ]
    if node_name in {"knowledge", "data", "clarify", "mixed_unsupported"}:
        events: list[tuple[str, dict[str, Any]]] = []
        if node_name == "data":
            events.append(
                (
                    "sql_validated",
                    {
                        "template_id": (patch.get("metadata") or {}).get(
                            "template_id"
                        ),
                    },
                )
            )
        evidence = patch.get("evidence")
        if evidence:
            events.append(("evidence", {"evidence": evidence}))
        if patch.get("answer"):
            events.append(
                (
                    "answer",
                    {
                        "status": patch.get("status"),
                        "answer": patch.get("answer"),
                        "error_code": patch.get("error_code"),
                    },
                )
            )
        return events
    if node_name == "validate_evidence" and patch.get("answer"):
        return [
            (
                "answer",
                {
                    "status": patch.get("status"),
                    "answer": patch.get("answer"),
                    "error_code": patch.get("error_code"),
                },
            )
        ]
    return []


def _summarize_history(history: list[dict[str, Any]]) -> str:
    """根据最近几轮对话生成简短摘要。"""
    return "\n".join(
        f"用户: {item.get('query', '')}\n助手: {item.get('answer', '')}"
        for item in history[-3:]
    )


def _to_response(state: AgentState) -> QueryResponse:
    """校验并序列化最终 Graph 状态，供 API 返回。"""
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
    """返回 ISO-8601 UTC 时间戳，供后续可观测性扩展使用。"""
    return datetime.now(UTC).isoformat()
