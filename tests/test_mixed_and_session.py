from __future__ import annotations

from app.container import AppContainer
from app.domain.models import Principal, QueryRequest, RunStatus


async def test_mixed_uses_whitelisted_plan(
    seeded_container: AppContainer,
    sales_principal: Principal,
) -> None:
    response = await seeded_container.workflow.run(
        request=QueryRequest(query="结合库存制度分析当前库存并给出要求"),
        principal=sales_principal,
    )
    assert response.status == RunStatus.ANSWERED
    assert response.plan is not None
    assert response.plan["plan_id"] == "policy_plus_inventory"
    assert response.review is not None and response.review["passed"] is True
    assert {item.kind.value for item in response.evidence} == {"document", "data"}


async def test_thread_history_is_reused_in_memory(
    seeded_container: AppContainer,
    sales_principal: Principal,
) -> None:
    first = await seeded_container.workflow.run(
        request=QueryRequest(
            query="销售总额口径是什么？",
            thread_id="thread-1",
        ),
        principal=sales_principal,
    )
    second = await seeded_container.workflow.run(
        request=QueryRequest(
            query="统计2026年7月销售额",
            thread_id="thread-1",
        ),
        principal=sales_principal,
    )
    assert first.thread_id == second.thread_id == "thread-1"
    assert second.run_id != first.run_id
