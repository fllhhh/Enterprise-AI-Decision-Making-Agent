"""容器和可信身份依赖。"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.container import AppContainer
from app.domain.errors import AuthenticationError
from app.domain.models import Principal

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> AppContainer:
    """返回进程级应用容器。"""
    return request.app.state.container


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    container: AppContainer = Depends(get_container),
) -> Principal:
    """将 Bearer Token 解码为可信 Principal。

    API 不会从 JSON 请求数据中接受用户或部门身份。
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("缺少 Bearer 身份令牌")
    return container.security.decode(credentials.credentials)
