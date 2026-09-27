"""基于库存和历史销量的确定性库存风险诊断。"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from typing import Any

from app.domain.models import Evidence, EvidenceKind, Principal, RunStatus
from app.infra.database import Database
from app.infra.permissions import PermissionService
from app.skills.base import SkillOutcome
from app.skills.data import QueryTemplateRegistry


class InventoryRiskSkill:
    def __init__(
        self,
        *,
        registry: QueryTemplateRegistry,
        database: Database,
        permission_service: PermissionService,
        lookback_days: int = 30,
        stale_after_days: int = 3,
        critical_days: float = 7.0,
        low_days: float = 14.0,
        overstock_days: float = 90.0,
    ) -> None:
        self._registry = registry
        self._database = database
        self._permission_service = permission_service
        self._lookback_days = lookback_days
        self._stale_after_days = stale_after_days
        self._critical_days = critical_days
        self._low_days = low_days
        self._overstock_days = overstock_days

    async def answer(self, *, query: str, principal: Principal) -> SkillOutcome:
        inventory = self._registry.get("inventory_balance")
        velocity = self._registry.get("inventory_velocity")
        assert inventory is not None and velocity is not None
        for template in (inventory, velocity):
            await self._permission_service.assert_template_allowed(principal, template.template_id)
            await self._permission_service.assert_view_allowed(principal, template.view_name)
        period_end = date.today()
        period_start = period_end - timedelta(days=self._lookback_days - 1)
        inventory_rows, sales_rows = await asyncio.gather(
            self._database.execute_template(inventory, {}, principal),
            self._database.execute_template(
                velocity,
                {"period_start": period_start, "period_end": period_end},
                principal,
            ),
        )
        sales_by_product = {str(row["product_id"]): row for row in sales_rows}
        risks = [
            self._assess(row, sales_by_product.get(str(row["product_id"])), period_end)
            for row in inventory_rows
        ]
        risks.sort(key=lambda item: (item["severity"], item["product_id"]))
        evidence = Evidence(
            evidence_id="E1",
            kind=EvidenceKind.RISK,
            source_id="inventory_risk",
            title="库存风险诊断",
            version="v0.3",
            locator=f"lookback={self._lookback_days}d",
            excerpt=json.dumps(risks[:10], ensure_ascii=False, default=str),
            score=1.0,
            metadata={
                "template_id": "inventory_risk",
                "row_count": len(risks),
                "lookback_days": self._lookback_days,
                "items": risks,
            },
        )
        if not risks:
            answer = "当前权限范围内没有可用于库存风险诊断的数据。[E1]"
        else:
            lines = [
                f"- {item['product_id']}：{item['risk_label']}；{item['reason']}"
                for item in risks
            ]
            answer = (
                f"库存风险诊断使用最近 {self._lookback_days} 天历史销量作为需求代理，"
                "并保留库存数据新鲜度提示 [E1]：\n" + "\n".join(lines)
            )
        return SkillOutcome(
            status=RunStatus.ANSWERED,
            answer=answer,
            evidence=[evidence],
            metadata={"template_id": "inventory_risk", "row_count": len(risks), "risk_items": risks},
        )

    def _assess(self, inventory: dict[str, Any], sales: dict[str, Any] | None, today: date) -> dict[str, Any]:
        product_id = str(inventory["product_id"])
        on_hand = float(inventory.get("quantity_on_hand") or 0)
        in_transit = float(inventory.get("quantity_in_transit") or 0)
        available = on_hand + in_transit
        sold = float((sales or {}).get("total_quantity") or 0)
        daily_sales = sold / self._lookback_days
        snapshot_raw = inventory.get("snapshot_date")
        snapshot = date.fromisoformat(str(snapshot_raw)) if snapshot_raw else None
        stale_days = (today - snapshot).days if snapshot else None
        is_stale = stale_days is None or stale_days > self._stale_after_days
        if daily_sales <= 0:
            days_cover = None
            level, severity = ("积压风险", 3) if available > 0 else ("无需求数据", 4)
            reason = f"近 {self._lookback_days} 天销量为零，可用库存 {available:g}"
        else:
            days_cover = available / daily_sales
            if available <= 0 or days_cover < self._critical_days:
                level, severity = "缺货风险", 0
            elif days_cover < self._low_days:
                level, severity = "低库存", 1
            elif days_cover > self._overstock_days:
                level, severity = "积压风险", 2
            else:
                level, severity = "库存健康", 3
            reason = f"可用库存 {available:g}，日均销量 {daily_sales:.2f}，可售 {days_cover:.1f} 天"
        if is_stale:
            reason += "；库存快照缺失或已过期"
        return {
            "product_id": product_id,
            "risk_label": level,
            "severity": severity,
            "quantity_on_hand": on_hand,
            "quantity_in_transit": in_transit,
            "average_daily_sales": round(daily_sales, 2),
            "days_cover": round(days_cover, 1) if days_cover is not None else None,
            "snapshot_date": snapshot.isoformat() if snapshot else None,
            "stale": is_stale,
            "reason": reason,
        }
