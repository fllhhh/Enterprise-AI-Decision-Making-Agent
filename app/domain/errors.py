from __future__ import annotations


class AgentError(Exception):
    code = "AGENT_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class AuthenticationError(AgentError):
    code = "AUTH_INVALID"


class ConfigurationError(AgentError):
    code = "CONFIGURATION_ERROR"


class DependencyUnavailableError(AgentError):
    code = "DEPENDENCY_UNAVAILABLE"


class QueryTimeoutError(AgentError):
    code = "QUERY_TIMEOUT"


class QueryExecutionError(AgentError):
    code = "QUERY_EXECUTION_FAILED"


class MissingSlotError(AgentError):
    code = "MISSING_SLOT"


class TemplateNotFoundError(AgentError):
    code = "TEMPLATE_NOT_FOUND"


class NoEvidenceError(AgentError):
    code = "NO_EVIDENCE"

