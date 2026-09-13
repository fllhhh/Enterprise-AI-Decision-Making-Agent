from __future__ import annotations

from app.container import AppContainer
from app.domain.models import Principal, QueryRequest, RunStatus


async def test_mixed_is_explicitly_unsupported(
    container: AppContainer,
    sales_principal: Principal,
) -> None:
    response = await container.workflow.run(
        request=QueryRequest(query="结合库存制度分析当前库存并给出要求"),
        principal=sales_principal,
    )
    assert response.status == RunStatus.UNSUPPORTED
    assert response.error is not None
    assert response.error.code == "MIXED_NOT_SUPPORTED"


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

