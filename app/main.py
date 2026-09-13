from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import Settings
from app.container import AppContainer
from app.domain.errors import (
    AgentError,
    AuthenticationError,
    DependencyUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
)
from app.infra.logging import configure_logging, trace_id_var

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    container: AppContainer | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    configure_logging(app_settings.log_level)
    app_container = container or AppContainer(app_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await app_container.startup()
        try:
            yield
        finally:
            await app_container.shutdown()

    application = FastAPI(
        title="Enterprise Decision Agent",
        version="0.1.0",
        description="v0.1 可信纵向切片",
        lifespan=lifespan,
    )
    application.state.container = app_container
    application.include_router(router)
    application.add_middleware(_TraceMiddleware)

    @application.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request,
        exc: AuthenticationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": {"code": exc.code, "message": exc.message}},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @application.exception_handler(DependencyUnavailableError)
    async def dependency_error_handler(
        request: Request,
        exc: DependencyUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @application.exception_handler(QueryTimeoutError)
    async def timeout_error_handler(
        request: Request,
        exc: QueryTimeoutError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=504,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @application.exception_handler(QueryExecutionError)
    async def query_error_handler(
        request: Request,
        exc: QueryExecutionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @application.exception_handler(AgentError)
    async def agent_error_handler(request: Request, exc: AgentError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @application.exception_handler(Exception)
    async def unknown_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_request_error")
        return JSONResponse(
            status_code=500,
            content={"detail": {"code": "INTERNAL_ERROR", "message": "服务内部错误"}},
        )

    return application


class _TraceMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        requested_trace_id = headers.get(b"x-trace-id", b"").decode("ascii", errors="ignore")
        trace_id = _safe_trace_id(requested_trace_id)
        token = trace_id_var.set(trace_id)

        async def send_with_trace(message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers = [
                    (key, value)
                    for key, value in response_headers
                    if key.lower() != b"x-trace-id"
                ]
                response_headers.append((b"x-trace-id", trace_id.encode("ascii")))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            trace_id_var.reset(token)


def _safe_trace_id(value: str) -> str:
    if value and len(value) <= 128 and all(character.isalnum() or character in "-_." for character in value):
        return value
    return str(uuid.uuid4())


app = create_app()
