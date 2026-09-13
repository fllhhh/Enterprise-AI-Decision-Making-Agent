from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import Settings
from app.container import AppContainer
from app.evaluation.runner import run_evaluation
from app.security.jwt import JWTManager


def main() -> None:
    parser = argparse.ArgumentParser(prog="enterprise-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest-demo",
        help="导入演示知识文档到 Chroma",
    )
    ingest_parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="演示文档目录，默认读取 DEMO_DOCS_PATH",
    )

    token_parser = subparsers.add_parser(
        "issue-token",
        help="签发本地演示 JWT",
    )
    token_parser.add_argument("--user", required=True)
    token_parser.add_argument("--department", required=True)
    token_parser.add_argument("--roles", default="employee")
    token_parser.add_argument("--ttl", type=int, default=3600)

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="执行 v0.1 离线评测",
    )
    evaluate_parser.add_argument("--mode", choices=("fake", "real"), default="fake")
    evaluate_parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/v0.1-evaluation.json"),
    )

    args = parser.parse_args()
    if args.command == "ingest-demo":
        asyncio.run(_ingest_demo(args.path))
    elif args.command == "issue-token":
        _issue_token(args)
    elif args.command == "evaluate":
        report = asyncio.run(run_evaluation(mode=args.mode, output_path=args.output))
        print(json.dumps(
            {
                "success": report.success,
                "passed": f"{report.passed}/{report.total}",
                "metrics": report.metrics,
                "gates": report.gates,
                "report": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        ))
        raise SystemExit(0 if report.success else 1)


async def _ingest_demo(path: Path | None) -> None:
    settings = Settings()
    if path is not None:
        settings = settings.model_copy(update={"demo_docs_path": path})
    container = AppContainer(settings)
    try:
        count = await container.ingest_demo_documents()
    finally:
        await container.shutdown()
    print(json.dumps({"ingested_chunks": count}, ensure_ascii=False))


def _issue_token(args: argparse.Namespace) -> None:
    settings = Settings()
    manager = JWTManager(settings)
    token, expires_at = manager.issue(
        user_id=args.user,
        department=args.department,
        roles=[role.strip() for role in args.roles.split(",") if role.strip()],
        ttl_seconds=args.ttl,
    )
    print(json.dumps(
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()

