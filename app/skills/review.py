"""回答提交前的确定性审校。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import Evidence, Route, RunStatus


@dataclass(frozen=True, slots=True)
class ReviewResult:
    passed: bool
    code: str
    message: str
    retryable: bool = False

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


class AnswerReviewer:
    """校验证据、引用、Mixed 分支覆盖和数据数字绑定。"""

    def review(
        self,
        *,
        route: Route,
        status: RunStatus,
        answer: str,
        evidence: list[Evidence],
        plan: dict | None = None,
    ) -> ReviewResult:
        if status != RunStatus.ANSWERED:
            return ReviewResult(True, "NOT_APPLICABLE", "非事实回答无需审校")
        if not evidence:
            return ReviewResult(False, "REVIEW_NO_EVIDENCE", "回答缺少证据", True)
        known = {item.evidence_id for item in evidence}
        cited = set(re.findall(r"\[([^\]]+)\]", answer))
        if not cited.intersection(known):
            return ReviewResult(False, "REVIEW_CITATION_MISSING", "回答未引用有效证据", True)
        if cited.difference(known):
            return ReviewResult(False, "REVIEW_CITATION_UNKNOWN", "回答引用了未知证据")
        if route == Route.DATA:
            evidence_text = " ".join(item.excerpt for item in evidence)
            answer_without_citations = re.sub(r"\[[^\]]+\]", "", answer)
            unsupported = [
                number
                for number in re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", answer_without_citations)
                if number not in evidence_text
            ]
            if unsupported:
                return ReviewResult(
                    False,
                    "REVIEW_NUMBER_UNSUPPORTED",
                    "数据回答包含无法由 Evidence 复核的数字",
                )
        if route == Route.MIXED:
            kinds = {item.kind.value for item in evidence}
            if "document" not in kinds or not kinds.intersection({"data", "risk"}):
                return ReviewResult(False, "REVIEW_PLAN_INCOMPLETE", "混合回答缺少计划要求的证据", True)
            if not plan:
                return ReviewResult(False, "REVIEW_PLAN_MISSING", "混合回答缺少白名单计划")
        return ReviewResult(True, "REVIEW_PASSED", "证据与引用检查通过")
