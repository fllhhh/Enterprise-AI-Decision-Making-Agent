from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.errors import AuthenticationError
from app.security.jwt import JWTManager


def test_jwt_round_trip() -> None:
    settings = Settings(
        app_env="test",
        jwt_secret="test-secret-with-at-least-32-characters",
    )
    manager = JWTManager(settings)
    token, _ = manager.issue(
        user_id="u-1",
        department="sales",
        roles=["employee"],
    )
    principal = manager.decode(token)
    assert principal.user_id == "u-1"
    assert principal.department == "sales"
    assert principal.roles == ("employee",)


def test_invalid_jwt_is_rejected() -> None:
    settings = Settings(
        app_env="test",
        jwt_secret="test-secret-with-at-least-32-characters",
    )
    with pytest.raises(AuthenticationError):
        JWTManager(settings).decode("not-a-token")

