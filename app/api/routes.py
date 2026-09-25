"""健康检查和 Agent 查询的 HTTP 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_container, get_principal
from app.container import AppContainer
from app.domain.models import (
    HealthResponse,
    FeedbackRequest,
    Principal,
    QueryRequest,
    QueryResponse,
    ThreadEvent,
    ThreadHistoryResponse,
)

router = APIRouter()


@router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """返回轻量服务描述，不启动 Agent 工作流。"""
    return {
        "service": "enterprise-agent",
        "version": "0.2.0",
        "docs": "/docs",
        "ui": "/ui",
    }


@router.get("/health/live", response_model=HealthResponse, tags=["health"])
async def live() -> HealthResponse:
    """报告进程存活状态，不检查外部依赖。"""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def ready(container: AppContainer = Depends(get_container)) -> HealthResponse:
    """报告 Embedding、向量库和 PostgreSQL 是否可用。"""
    checks = await container.readiness()
    if not all(checks.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "checks": checks,
            },
        )
    return HealthResponse(status="ready", checks=checks)


@router.post(
    "/api/v1/query",
    response_model=QueryResponse,
    tags=["agent"],
    summary="执行知识问答或受控数据查询",
)
async def query(
    payload: QueryRequest,
    principal: Principal = Depends(get_principal),
    container: AppContainer = Depends(get_container),
) -> QueryResponse:
    """校验身份并执行一次 Agent 工作流。"""
    return await container.workflow.run(request=payload, principal=principal)


@router.post(
    "/api/v1/query/stream",
    tags=["agent"],
    summary="流式执行知识问答或受控数据查询",
)
async def query_stream(
    payload: QueryRequest,
    principal: Principal = Depends(get_principal),
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    """以 Server-Sent Events 推送运行阶段和最终结果。"""

    async def event_source():
        async for event in container.workflow.stream(
            request=payload,
            principal=principal,
        ):
            await container.app_repository.record_thread_event(
                thread_id=event["thread_id"],
                run_id=event["run_id"],
                trace_id=event["trace_id"],
                user_id=principal.user_id,
                event_type=event["event"],
                payload=event["payload"],
            )
            if event["event"] == "completed":
                await container.app_repository.record_audit(
                    trace_id=event["trace_id"],
                    run_id=event["run_id"],
                    thread_id=event["thread_id"],
                    user_id=principal.user_id,
                    event_type="agent_run_completed",
                    payload=event["payload"],
                )
            yield _sse_event(event)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/api/v1/threads/{thread_id}",
    response_model=ThreadHistoryResponse,
    tags=["agent"],
    summary="读取会话事件历史",
)
async def thread_history(
    thread_id: str,
    principal: Principal = Depends(get_principal),
    container: AppContainer = Depends(get_container),
) -> ThreadHistoryResponse:
    """返回由流式端点持久化的会话事件。"""
    events = await container.app_repository.list_thread_events(thread_id)
    return ThreadHistoryResponse(
        thread_id=thread_id,
        events=[
            ThreadEvent.model_validate(event)
            for event in events
        ],
    )


@router.post(
    "/api/v1/feedback",
    response_model=dict[str, str],
    tags=["agent"],
    summary="提交回答反馈",
)
async def feedback(
    payload: FeedbackRequest,
    principal: Principal = Depends(get_principal),
    container: AppContainer = Depends(get_container),
) -> dict[str, str]:
    """保存用户对一次运行的评分和评论。"""
    await container.app_repository.save_feedback(
        run_id=payload.run_id,
        thread_id=payload.thread_id,
        user_id=principal.user_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    return {"status": "accepted"}


def _sse_event(event: dict) -> str:
    """将事件对象格式化为单条 SSE 消息。"""
    import json

    data = json.dumps(event, ensure_ascii=False)
    return f"event: {event['event']}\ndata: {data}\n\n"
