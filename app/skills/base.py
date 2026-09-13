from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import Evidence, RunStatus


@dataclass(slots=True)
class SkillOutcome:
    status: RunStatus
    answer: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

