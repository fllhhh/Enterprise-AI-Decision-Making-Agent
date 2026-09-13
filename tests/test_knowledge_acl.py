from __future__ import annotations

from app.container import AppContainer
from app.domain.models import Principal, RunStatus


async def test_authorized_document_is_retrieved_with_evidence(
    seeded_container: AppContainer,
    sales_principal: Principal,
) -> None:
    response = await seeded_container.workflow.run(
        request=__import__("app.domain.models", fromlist=["QueryRequest"]).QueryRequest(
            query="销售总额按哪个日期统计？"
        ),
        principal=sales_principal,
    )

    assert response.status == RunStatus.ANSWERED
    assert response.evidence
    assert response.evidence[0].source_id == "doc-sales-policy"
    assert f"[{response.evidence[0].evidence_id}]" in response.answer


async def test_unauthorized_document_is_not_retrieved(
    seeded_container: AppContainer,
    sales_principal: Principal,
) -> None:
    response = await seeded_container.workflow.run(
        request=__import__("app.domain.models", fromlist=["QueryRequest"]).QueryRequest(
            query="员工差旅住宿报销标准是什么？"
        ),
        principal=sales_principal,
    )

    assert response.status == RunStatus.CLARIFY
    assert all(item.source_id != "doc-travel-policy" for item in response.evidence)


async def test_executive_can_access_restricted_document(
    seeded_container: AppContainer,
) -> None:
    executive = Principal(
        user_id="u-exec",
        department="headquarter",
        roles=("exec",),
        issuer="enterprise-agent-local",
        audience="enterprise-agent-api",
    )
    response = await seeded_container.workflow.run(
        request=__import__("app.domain.models", fromlist=["QueryRequest"]).QueryRequest(
            query="员工差旅住宿报销标准是什么？"
        ),
        principal=executive,
    )
    assert response.status == RunStatus.ANSWERED
    assert response.evidence[0].source_id == "doc-travel-policy"

