from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from jwt import InvalidTokenError

from app.config import Settings
from app.domain.errors import AuthenticationError
from app.domain.models import Principal


class JWTManager:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret.get_secret_value()
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience

    def issue(
        self,
        *,
        user_id: str,
        department: str,
        roles: list[str] | tuple[str, ...],
        ttl_seconds: int = 3600,
    ) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        payload = {
            "sub": user_id,
            "department": department,
            "roles": list(roles),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": now,
            "exp": expires_at,
        }
        token = jwt.encode(payload, self._secret, algorithm="HS256")
        return token, expires_at

    def decode(self, token: str) -> Principal:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "department", "roles", "iss", "aud", "iat", "exp"]},
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("身份令牌无效或已过期") from exc

        roles = payload.get("roles")
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise AuthenticationError("身份令牌中的 roles 格式无效")

        return Principal(
            user_id=str(payload["sub"]),
            department=str(payload["department"]),
            roles=tuple(roles),
            issuer=str(payload["iss"]),
            audience=str(payload["aud"]),
        )

