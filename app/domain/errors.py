"""由 API 层转换为 HTTP 响应的领域异常。"""

from __future__ import annotations


class AgentError(Exception):
    """可预期应用失败的基础异常。"""

    code = "AGENT_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        """保存安全消息和可选的细分错误码。"""
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class AuthenticationError(AgentError):
    """当 JWT 缺失、格式错误或过期时抛出。"""

    code = "AUTH_INVALID"


class ConfigurationError(AgentError):
    """运行时依赖或配置缺失时抛出。"""

    code = "CONFIGURATION_ERROR"


class DependencyUnavailableError(AgentError):
    """外部依赖暂时不可用时抛出。"""

    code = "DEPENDENCY_UNAVAILABLE"


class QueryTimeoutError(AgentError):
    """只读数据查询超过配置超时时间时抛出。"""

    code = "QUERY_TIMEOUT"


class QueryExecutionError(AgentError):
    """已经校验的查询在 PostgreSQL 中执行失败时抛出。"""

    code = "QUERY_EXECUTION_FAILED"


class MissingSlotError(AgentError):
    """数据模板缺少必要参数时抛出。"""

    code = "MISSING_SLOT"


class TemplateNotFoundError(AgentError):
    """请求的数据模板未注册时抛出。"""

    code = "TEMPLATE_NOT_FOUND"


class NoEvidenceError(AgentError):
    """没有可访问且相关的证据时抛出。"""

    code = "NO_EVIDENCE"
