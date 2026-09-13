from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.container import AppContainer
from app.domain.models import Principal
from app.infra.fakes import (
    FakeChatModel,
    FakeDatabase,
    FakeEmbeddingProvider,
    InMemoryVectorStore,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        jwt_secret="test-secret-with-at-least-32-characters",
        demo_docs_path="app/resources/demo_docs",
    )


@pytest.fixture
def container(settings: Settings) -> AppContainer:
    return AppContainer(
        settings,
        chat_model=FakeChatModel(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        database=FakeDatabase(),
    )


@pytest.fixture
async def seeded_container(container: AppContainer) -> AppContainer:
    await container.ingest_demo_documents()
    return container


@pytest.fixture
def sales_principal() -> Principal:
    return Principal(
        user_id="u-sales",
        department="sales",
        roles=("employee",),
        issuer="enterprise-agent-local",
        audience="enterprise-agent-api",
    )


@pytest.fixture
def hr_principal() -> Principal:
    return Principal(
        user_id="u-hr",
        department="hr",
        roles=("hr_manager",),
        issuer="enterprise-agent-local",
        audience="enterprise-agent-api",
    )


@pytest.fixture
def sales_token(settings: Settings, sales_principal: Principal) -> str:
    token, _ = container_token(settings, sales_principal)
    return token


def container_token(settings: Settings, principal: Principal) -> tuple[str, datetime]:
    from app.security.jwt import JWTManager

    return JWTManager(settings).issue(
        user_id=principal.user_id,
        department=principal.department,
        roles=list(principal.roles),
        ttl_seconds=int(
            (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            - datetime.now(UTC).timestamp()
        ),
    )

