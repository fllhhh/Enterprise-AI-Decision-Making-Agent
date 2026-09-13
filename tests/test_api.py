from __future__ import annotations

import httpx

from app.container import AppContainer
from app.main import create_app


async def test_query_api_requires_jwt(
    settings,
    seeded_container: AppContainer,
) -> None:
    app = create_app(settings=settings, container=seeded_container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/query", json={"query": "销售制度是什么？"})
    assert response.status_code == 401


async def test_query_api_returns_trace_and_evidence(
    settings,
    seeded_container: AppContainer,
    sales_token: str,
) -> None:
    app = create_app(settings=settings, container=seeded_container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/query",
            json={"query": "销售总额口径是什么？"},
            headers={
                "Authorization": f"Bearer {sales_token}",
                "X-Trace-ID": "trace-test-001",
            },
        )
    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-test-001"
    body = response.json()
    assert body["trace_id"] == "trace-test-001"
    assert body["status"] == "answered"
    assert body["evidence"]


async def test_live_health(settings, seeded_container: AppContainer) -> None:
    app = create_app(settings=settings, container=seeded_container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_ready_health_with_fakes(settings, seeded_container: AppContainer) -> None:
    app = create_app(settings=settings, container=seeded_container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {
        "embedding": True,
        "vector_store": True,
        "database": True,
    }
