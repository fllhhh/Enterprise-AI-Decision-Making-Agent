from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_container, get_principal
from app.container import AppContainer
from app.domain.models import (
    HealthResponse,
    Principal,
    QueryRequest,
    QueryResponse,
)

router = APIRouter()


@router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": "enterprise-agent",
        "version": "0.1.0",
        "docs": "/docs",
    }


@router.get("/health/live", response_model=HealthResponse, tags=["health"])
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def ready(container: AppContainer = Depends(get_container)) -> HealthResponse:
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
    return await container.workflow.run(request=payload, principal=principal)

