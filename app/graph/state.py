"""在 LangGraph 节点之间传递的共享状态。"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """同一会话线程的状态契约。

    ``prepare`` 会清理每一轮的临时字段；会话字段会被保留，
    便于后续请求使用最近上下文。
    """

    # 当前请求和可信身份快照。
    query: str
    principal: dict[str, Any]
    # 会话记忆。v0.1 只保存在当前进程内。
    conversation_summary: str
    history: list[dict[str, Any]]
    # 供条件边使用的 Router 输出。
    route: str
    route_confidence: float
    route_reason: str
    # 当前业务结果和支持该结果的证据。
    status: str
    answer: str
    evidence: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    # 返回给调用方并写入日志的关联标识。
    run_id: str
    trace_id: str
    thread_id: str
    # 路由相关元数据，例如数据模板 ID 和返回行数。
    metadata: dict[str, Any]
