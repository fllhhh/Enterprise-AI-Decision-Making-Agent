"""v0.3 Mixed 请求的白名单规划器。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    skill: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    plan_id: str
    title: str
    steps: tuple[PlanStep, ...]

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "steps": [
                {"step_id": step.step_id, "skill": step.skill, "required": step.required}
                for step in self.steps
            ],
        }


class WhitelistPlanner:
    """只返回服务端登记的计划，绝不接受模型生成的任意工具链。"""

    _PLANS = {
        "policy_plus_sales": ExecutionPlan(
            "policy_plus_sales",
            "销售数据与制度依据",
            (PlanStep("policy", "knowledge"), PlanStep("sales", "data")),
        ),
        "policy_plus_inventory": ExecutionPlan(
            "policy_plus_inventory",
            "库存数据与制度依据",
            (PlanStep("policy", "knowledge"), PlanStep("inventory", "data")),
        ),
        "inventory_risk_with_policy": ExecutionPlan(
            "inventory_risk_with_policy",
            "库存风险与制度依据",
            (PlanStep("policy", "knowledge"), PlanStep("risk", "inventory_risk")),
        ),
    }

    def plan(self, query: str) -> ExecutionPlan | None:
        normalized = query.lower()
        if any(term in normalized for term in ("风险", "缺货", "积压", "滞销")):
            return self._PLANS["inventory_risk_with_policy"]
        if any(term in normalized for term in ("库存", "在库", "在途", "结余")):
            return self._PLANS["policy_plus_inventory"]
        if any(term in normalized for term in ("销售", "订单", "金额", "畅销", "排名")):
            return self._PLANS["policy_plus_sales"]
        return None

    def get(self, plan_id: str) -> ExecutionPlan | None:
        return self._PLANS.get(plan_id)

    def all(self) -> tuple[ExecutionPlan, ...]:
        return tuple(self._PLANS.values())
