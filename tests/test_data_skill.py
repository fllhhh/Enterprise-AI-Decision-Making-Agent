from __future__ import annotations

from app.container import AppContainer
from app.domain.models import Principal, QueryRequest, Route, RunStatus


async def test_sales_summary_uses_approved_template(
    container: AppContainer,
    sales_principal: Principal,
) -> None:
    response = await container.workflow.run(
        request=QueryRequest(query="统计2026年7月销售额"),
        principal=sales_principal,
    )
    assert response.route == Route.DATA
    assert response.status == RunStatus.ANSWERED
    assert response.evidence[0].source_id == "sales_summary"
    assert "128000.0" in response.answer


async def test_data_query_requires_date_range(
    container: AppContainer,
    sales_principal: Principal,
) -> None:
    response = await container.workflow.run(
        request=QueryRequest(query="统计销售额"),
        principal=sales_principal,
    )
    assert response.status == RunStatus.CLARIFY
    assert response.error is not None
    assert response.error.code == "MISSING_SLOT"


async def test_unsupported_data_query_is_clarified(
    container: AppContainer,
    sales_principal: Principal,
) -> None:
    response = await container.workflow.run(
        request=QueryRequest(query="查询银河指标数量"),
        principal=sales_principal,
    )
    assert response.status == RunStatus.CLARIFY
    assert not response.evidence


async def test_client_cannot_inject_permission_argument(
    container: AppContainer,
    sales_principal: Principal,
) -> None:
    container.chat_model.json_responses.append(
        {
            "template_id": "sales_summary",
            "arguments": {
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "department_id": "finance",
            },
            "confidence": 0.99,
            "reason": "attempted privilege escalation",
        }
    )
    response = await container.workflow.run(
        request=QueryRequest(query="统计2026年7月销售额"),
        principal=sales_principal,
    )

    assert response.status == RunStatus.CLARIFY
    assert response.error is not None
    assert response.error.code == "MISSING_SLOT"
    assert not response.evidence
