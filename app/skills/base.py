"""知识 Skill 和数据 Skill 共用的结果结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import Evidence, RunStatus


@dataclass(slots=True)
class SkillOutcome:
    """供 LangGraph 状态更新使用的统一结果。"""

    status: RunStatus
    answer: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
