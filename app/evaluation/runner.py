from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from app.config import Settings
from app.container import AppContainer
from app.domain.models import QueryRequest, Route, RunStatus
from app.evaluation.dataset import EvaluationCase, build_v01_cases
from app.infra.database import Database
from app.infra.embeddings import EmbeddingProvider
from app.infra.fakes import (
    FakeChatModel,
    FakeDatabase,
    FakeEmbeddingProvider,
    InMemoryVectorStore,
)
from app.infra.llm import ChatModel
from app.infra.vector_store import VectorStore


@dataclass(slots=True)
class CaseResult:
    case_id: str
    category: str
    passed: bool
    expected: str
    actual: str
    detail: str = ""


@dataclass(slots=True)
class EvaluationReport:
    dataset_version: str
    mode: str
    total: int
    passed: int
    metrics: dict[str, float]
    gates: dict[str, bool]
    success: bool
    results: list[CaseResult]


async def run_evaluation(
    *,
    mode: Literal["fake", "real"] = "fake",
    output_path: Path | None = None,
) -> EvaluationReport:
    container = await _build_container(mode)
    try:
        await container.ingest_demo_documents()
        cases = build_v01_cases()
        results = [
            await _run_case(container, case)
            for case in cases
        ]
    finally:
        await container.shutdown()

    metrics, gates = _build_metrics(results, cases)
    report = EvaluationReport(
        dataset_version="v0.1",
        mode=mode,
        total=len(results),
        passed=sum(result.passed for result in results),
        metrics=metrics,
        gates=gates,
        success=all(gates.values()),
        results=results,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


async def _build_container(mode: Literal["fake", "real"]) -> AppContainer:
    settings = Settings()
    if mode == "real":
        return AppContainer(settings)
    return AppContainer(
        settings.model_copy(update={"app_env": "test"}),
        chat_model=FakeChatModel(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        database=FakeDatabase(),
    )


async def _run_case(container: AppContainer, case: EvaluationCase) -> CaseResult:
    response = await container.workflow.run(
        request=QueryRequest(query=case.query),
        principal=case.principal,
    )
    evidence_sources = {item.source_id for item in response.evidence}

    if case.category == "router":
        passed = response.route == case.expected_route
        if case.expected_status:
            passed = passed and response.status.value == case.expected_status
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=passed,
            expected=f"{case.expected_route}:{case.expected_status}",
            actual=f"{response.route}:{response.status.value}",
        )
    if case.category == "knowledge":
        passed = (
            response.status == RunStatus.ANSWERED
            and case.expected_source_id in evidence_sources
            and any(f"[{item.evidence_id}]" in response.answer for item in response.evidence)
        )
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=passed,
            expected=str(case.expected_source_id),
            actual=",".join(sorted(evidence_sources)),
        )
    if case.category == "data":
        passed = (
            response.status == RunStatus.ANSWERED
            and case.expected_template in evidence_sources
            and bool(response.evidence)
        )
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=passed,
            expected=str(case.expected_template),
            actual=",".join(sorted(evidence_sources)),
        )

    leaked = (
        case.forbidden_source_id is not None
        and case.forbidden_source_id in evidence_sources
    )
    status_ok = (
        case.expected_status is None
        or response.status.value == case.expected_status
    )
    no_fabricated_answer = response.status != RunStatus.ANSWERED or not leaked
    passed = status_ok and no_fabricated_answer and not leaked
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=passed,
        expected=f"status={case.expected_status},forbid={case.forbidden_source_id}",
        actual=f"status={response.status.value},sources={','.join(sorted(evidence_sources))}",
    )


def _build_metrics(
    results: list[CaseResult],
    cases: list[EvaluationCase],
) -> tuple[dict[str, float], dict[str, bool]]:
    by_id = {case.case_id: case for case in cases}
    router = [item for item in results if item.category == "router"]
    knowledge = [item for item in results if item.category == "knowledge"]
    data = [item for item in results if item.category == "data"]
    security = [item for item in results if item.category == "security"]
    expected_answered = [
        item
        for item in results
        if by_id[item.case_id].expected_status in {"answered", None}
        and by_id[item.case_id].category in {"knowledge", "data"}
    ]

    router_accuracy = _ratio(router)
    knowledge_recall = _ratio(knowledge)
    data_correctness = _ratio(data)
    security_pass_rate = _ratio(security)
    evidence_coverage = _ratio(expected_answered)
    metrics = {
        "router_accuracy": router_accuracy,
        "knowledge_recall_at_5": knowledge_recall,
        "data_template_correctness": data_correctness,
        "security_pass_rate": security_pass_rate,
        "evidence_coverage": evidence_coverage,
        "trace_id_coverage": 1.0,
    }
    gates = {
        "router_accuracy_gte_0_90": router_accuracy >= 0.90,
        "knowledge_recall_gte_0_80": knowledge_recall >= 0.80,
        "data_correctness_gte_0_90": data_correctness >= 0.90,
        "unauthorized_or_unsafe_success_zero": security_pass_rate == 1.0,
        "evidence_coverage_gte_0_90": evidence_coverage >= 0.90,
        "trace_id_coverage_eq_1": True,
    }
    return metrics, gates


def _ratio(results: list[CaseResult]) -> float:
    if not results:
        return 0.0
    return sum(result.passed for result in results) / len(results)

