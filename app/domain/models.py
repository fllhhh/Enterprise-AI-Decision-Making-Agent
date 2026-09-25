"""公共领域契约，供 API、Graph 和业务 Skill 共用。

本模块中的模型只描述数据，不描述实现细节。它们在系统边界完成校验，
并可序列化到 LangGraph 状态中。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Route(StrEnum):
    """支持的一级请求路由。"""

    KNOWLEDGE = "knowledge"
    DATA = "data"
    MIXED = "mixed"
    CLARIFY = "clarify"


class RunStatus(StrEnum):
    """一次工作流运行对用户可见的结果状态。"""

    ANSWERED = "answered"
    CLARIFY = "clarify"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class EvidenceKind(StrEnum):
    """表示 Evidence 来源类别的枚举。"""

    DOCUMENT = "document"
    DATA = "data"


class Evidence(BaseModel):
    """支撑答案的可追溯来源材料。

    ``source_id`` 标识文档或查询模板；``locator`` 指向具体页码、章节或模板调用。
    答案只能引用 Evidence ID，不能把模型原始断言当作证据。
    """

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
    """返回给客户端的稳定、可机器读取错误信息。"""

    code: str
    message: str


class QueryRequest(BaseModel):
    """公共查询接口的已校验输入。"""

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

    # 自然语言问题。服务端只把它当作数据，不把它当作 SQL 或可执行指令。
    query: str = Field(min_length=1, max_length=2000)
    # 可选会话标识。未提供时由工作流生成 UUID。
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class QueryResponse(BaseModel):
    """经过路由、工具执行和证据校验后的最终响应。"""

    run_id: str
    thread_id: str
    trace_id: str
    route: Route
    status: RunStatus
    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
    error: ErrorDetail | None = None


class Principal(BaseModel):
    """从已验证 JWT 派生的可信身份，不来自请求字段。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    department: str
    roles: tuple[str, ...] = ()
    issuer: str
    audience: str

    @property
    def is_executive(self) -> bool:
        """判断该身份是否可以查询全部部门。"""
        return "exec" in self.roles or "admin" in self.roles


class TokenResponse(BaseModel):
    """本地开发 Token 响应。"""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class RouterDecision(BaseModel):
    """表示 Router 输出的结构化分类结果。"""

    route: Route
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class TemplateDecision(BaseModel):
    """模型或规则兜底输出的数据结构化模板选择结果。"""

    template_id: str | None
    arguments: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class HealthResponse(BaseModel):
    """存活或就绪检查响应。"""

    status: str
    checks: dict[str, bool] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    """用户对一次运行的评分和可选评论。"""

    run_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ThreadEvent(BaseModel):
    """持久化的流式会话事件。"""

    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ThreadHistoryResponse(BaseModel):
    """按时间顺序返回的会话历史。"""

    thread_id: str
    events: list[ThreadEvent] = Field(default_factory=list)
