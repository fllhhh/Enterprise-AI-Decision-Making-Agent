from __future__ import annotations

from app.evaluation.dataset import build_v01_cases
from app.evaluation.runner import run_evaluation


def test_evaluation_dataset_has_required_distribution() -> None:
    cases = build_v01_cases()
    counts = {
        category: sum(case.category == category for case in cases)
        for category in ("router", "knowledge", "data", "security")
    }
    assert len(cases) == 90
    assert counts == {
        "router": 30,
        "knowledge": 25,
        "data": 20,
        "security": 15,
    }


async def test_fake_evaluation_passes_all_gates(tmp_path) -> None:
    report = await run_evaluation(
        mode="fake",
        output_path=tmp_path / "evaluation.json",
    )
    assert report.total == 90
    assert all(report.gates.values()), report
    assert report.success

