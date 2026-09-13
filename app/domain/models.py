from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Route(StrEnum):
    KNOWLEDGE = "knowledge"
    DATA = "data"
    MIXED = "mixed"
    CLARIFY = "clarify"


class RunStatus(StrEnum):
    ANSWERED = "answered"
    CLARIFY = "clarify"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class EvidenceKind(StrEnum):
    DOCUMENT = "document"
    DATA = "data"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    kind: EvidenceKind
    source_id: str
    title: str
    version: str
    locator: str
    excerpt: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str


class QueryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "query": "华东区上个月销售额是多少？",
                    "thread_id": "demo-thread-001",
                }
            ]
        }
    )

    query: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class QueryResponse(BaseModel):
    run_id: str
    thread_id: str
    trace_id: str
    route: Route
    status: RunStatus
    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
    error: ErrorDetail | None = None


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    department: str
    roles: tuple[str, ...] = ()
    issuer: str
    audience: str

    @property
    def is_executive(self) -> bool:
        return "exec" in self.roles or "admin" in self.roles


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class RouterDecision(BaseModel):
    route: Route
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class TemplateDecision(BaseModel):
    template_id: str | None
    arguments: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, bool] = Field(default_factory=dict)

