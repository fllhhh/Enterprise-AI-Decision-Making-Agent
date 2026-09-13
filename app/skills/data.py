from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from app.domain.errors import DependencyUnavailableError
from app.domain.models import (
    Evidence,
    EvidenceKind,
    Principal,
    RunStatus,
    TemplateDecision,
)
from app.domain.query_templates import ArgumentType, QueryTemplate, TemplateArgument
from app.infra.database import Database
from app.infra.llm import ChatModel
from app.skills.base import SkillOutcome

logger = logging.getLogger(__name__)

_SALES_SUMMARY_SQL = """
SELECT /*+ MAX_EXECUTION_TIME(3000) */
       DATE_FORMAT(order_date, '%Y-%m') AS period,
       SUM(amount) AS total_amount,
       COUNT(*) AS order_count
FROM v_ai_sales_orders
WHERE (:include_all_departments = 1 OR department_id = :department_id)
  AND order_date BETWEEN :period_start AND :period_end
GROUP BY DATE_FORMAT(order_date, '%Y-%m')
ORDER BY period
LIMIT :row_limit
""".strip()

_TOP_PRODUCTS_SQL = """
SELECT /*+ MAX_EXECUTION_TIME(3000) */
       product_id,
       SUM(quantity) AS total_quantity,
       SUM(amount) AS total_amount
FROM v_ai_sales_orders
WHERE (:include_all_departments = 1 OR department_id = :department_id)
  AND order_date BETWEEN :period_start AND :period_end
GROUP BY product_id
ORDER BY total_amount DESC
LIMIT :top_n
""".strip()

_INVENTORY_BALANCE_SQL = """
SELECT /*+ MAX_EXECUTION_TIME(3000) */
       product_id,
       SUM(quantity_on_hand) AS quantity_on_hand,
       SUM(quantity_in_transit) AS quantity_in_transit
FROM v_ai_inventory_snapshots
WHERE (:include_all_departments = 1 OR department_id = :department_id)
GROUP BY product_id
ORDER BY quantity_on_hand DESC
LIMIT :row_limit
""".strip()


class QueryTemplateRegistry:
    def __init__(
        self,
        *,
        timeout_seconds: float = 3.0,
        max_rows: int = 200,
    ) -> None:
        self._templates = {
            template.template_id: template
            for template in (
                QueryTemplate(
                    template_id="sales_summary",
                    title="销售汇总",
                    description="按月份汇总指定日期范围内的销售额和订单量",
                    sql=_SALES_SUMMARY_SQL,
                    arguments=(
                        TemplateArgument(
                            "period_start",
                            ArgumentType.DATE,
                            True,
                            "开始日期，格式 YYYY-MM-DD",
                        ),
                        TemplateArgument(
                            "period_end",
                            ArgumentType.DATE,
                            True,
                            "结束日期，格式 YYYY-MM-DD",
                        ),
                    ),
                    timeout_seconds=timeout_seconds,
                    max_rows=max_rows,
                ),
                QueryTemplate(
                    template_id="top_products",
                    title="畅销商品",
                    description="按日期范围统计销售额最高的商品",
                    sql=_TOP_PRODUCTS_SQL,
                    arguments=(
                        TemplateArgument(
                            "period_start",
                            ArgumentType.DATE,
                            True,
                            "开始日期，格式 YYYY-MM-DD",
                        ),
                        TemplateArgument(
                            "period_end",
                            ArgumentType.DATE,
                            True,
                            "结束日期，格式 YYYY-MM-DD",
                        ),
                        TemplateArgument(
                            "top_n",
                            ArgumentType.INTEGER,
                            False,
                            "返回数量，范围 1 到 50",
                            default=5,
                        ),
                    ),
                    timeout_seconds=timeout_seconds,
                    max_rows=max_rows,
                ),
                QueryTemplate(
                    template_id="inventory_balance",
                    title="库存结余",
                    description="查询当前商品的在库数量和在途数量",
                    sql=_INVENTORY_BALANCE_SQL,
                    arguments=(),
                    timeout_seconds=timeout_seconds,
                    max_rows=max_rows,
                ),
            )
        }

    def get(self, template_id: str) -> QueryTemplate | None:
        return self._templates.get(template_id)

    def all(self) -> list[QueryTemplate]:
        return list(self._templates.values())

    def prompt_description(self) -> str:
        return "\n".join(template.prompt_description() for template in self.all())


class DataSkill:
    def __init__(
        self,
        *,
        chat_model: ChatModel,
        registry: QueryTemplateRegistry,
        database: Database,
        confidence_threshold: float = 0.70,
    ) -> None:
        self._chat_model = chat_model
        self._registry = registry
        self._database = database
        self._confidence_threshold = confidence_threshold

    async def answer(self, *, query: str, principal: Principal) -> SkillOutcome:
        decision = await self._select_template(query)
        if not decision.template_id:
            if decision.confidence < self._confidence_threshold:
                return _clarify(
                    "查询意图不够明确，请补充指标和时间范围。",
                    "LOW_CONFIDENCE",
                )
            return _clarify("当前只支持销售汇总、畅销商品和库存结余查询。", "TEMPLATE_NOT_FOUND")
        template = self._registry.get(decision.template_id)
        if template is None:
            if decision.confidence < self._confidence_threshold:
                return _clarify(
                    "查询意图不够明确，请补充指标和时间范围。",
                    "LOW_CONFIDENCE",
                )
            return _clarify("请求的数据指标不在当前白名单内。", "TEMPLATE_NOT_FOUND")

        try:
            arguments = _validate_arguments(template, decision.arguments)
        except ValueError as exc:
            return _clarify(str(exc), "MISSING_SLOT")
        if decision.confidence < self._confidence_threshold:
            return _clarify(
                "查询意图不够明确，请补充指标和时间范围。",
                "LOW_CONFIDENCE",
            )

        rows = await self._database.execute_template(template, arguments, principal)
        evidence = _data_evidence(template, arguments, rows)
        answer = _render_answer(template.template_id, rows)
        return SkillOutcome(
            status=RunStatus.ANSWERED,
            answer=answer,
            evidence=[evidence],
            metadata={
                "template_id": template.template_id,
                "arguments": arguments,
                "row_count": len(rows),
            },
        )

    async def _select_template(self, query: str) -> TemplateDecision:
        prompt = (
            "请从以下白名单模板中选择一个最匹配的数据查询模板。\n"
            f"{self._registry.prompt_description()}\n\n"
            f"当前日期：{date.today().isoformat()}\n"
            "只输出 JSON："
            '{"template_id":"模板ID或null","arguments":{},'
            '"confidence":0.0,"reason":"..."}\n'
            "日期参数必须转换为 YYYY-MM-DD。用户未给出日期时不要猜测。"
            f"\n用户问题：{query}"
        )
        try:
            result = await self._chat_model.generate_json(
                prompt,
                system_prompt=(
                    "你是企业数据查询模板选择器。只能选择模板并提取参数，"
                    "不得生成 SQL、表名、权限条件或执行任何操作。"
                ),
            )
            return TemplateDecision.model_validate(result)
        except DependencyUnavailableError:
            fallback = _rule_template(query)
            if fallback is None:
                raise
            return fallback


def _rule_template(query: str) -> TemplateDecision | None:
    if any(term in query for term in ("库存", "在库", "在途", "结余")):
        return TemplateDecision(
            template_id="inventory_balance",
            arguments={},
            confidence=0.85,
            reason="命中库存关键词",
        )
    if any(term in query for term in ("畅销", "排名", "最高", "top", "TOP")):
        return TemplateDecision(
            template_id="top_products",
            arguments={},
            confidence=0.55,
            reason="命中排名关键词，但缺少日期参数",
        )
    if any(term in query for term in ("销售", "金额", "订单", "汇总", "统计")):
        return TemplateDecision(
            template_id="sales_summary",
            arguments={},
            confidence=0.55,
            reason="命中销售关键词，但缺少日期参数",
        )
    return None


def _validate_arguments(
    template: QueryTemplate,
    raw_arguments: dict[str, Any],
) -> dict[str, Any]:
    allowed_names = {argument.name for argument in template.arguments}
    unexpected = set(raw_arguments).difference(allowed_names)
    if unexpected:
        raise ValueError(f"查询包含未允许的参数: {', '.join(sorted(unexpected))}")

    values: dict[str, Any] = {}
    for argument in template.arguments:
        if argument.name in raw_arguments and raw_arguments[argument.name] not in (None, ""):
            raw_value = raw_arguments[argument.name]
        else:
            raw_value = argument.default
        if raw_value is None:
            if argument.required:
                raise ValueError(f"缺少必要参数: {argument.name}")
            continue
        values[argument.name] = _convert_argument(argument, raw_value)

    if "period_start" in values and "period_end" in values:
        start = values["period_start"]
        end = values["period_end"]
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        if (end - start).days > 366:
            raise ValueError("查询日期范围不能超过 366 天")
    if "top_n" in values and not 1 <= values["top_n"] <= 50:
        raise ValueError("top_n 必须在 1 到 50 之间")
    return values


def _convert_argument(argument: TemplateArgument, value: Any) -> Any:
    if argument.argument_type == ArgumentType.DATE:
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"{argument.name} 必须为 YYYY-MM-DD") from exc
    if argument.argument_type == ArgumentType.INTEGER:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{argument.name} 必须为整数") from exc
    raise ValueError(f"不支持的参数类型: {argument.argument_type}")


def _data_evidence(
    template: QueryTemplate,
    arguments: dict[str, Any],
    rows: list[dict[str, Any]],
) -> Evidence:
    safe_arguments = {key: str(value) for key, value in arguments.items()}
    excerpt = json.dumps(rows[:5], ensure_ascii=False, default=str)
    return Evidence(
        evidence_id="E1",
        kind=EvidenceKind.DATA,
        source_id=template.template_id,
        title=template.title,
        version="v0.1",
        locator=f"template={template.template_id}",
        excerpt=excerpt,
        score=1.0,
        metadata={
            "template_id": template.template_id,
            "arguments": safe_arguments,
            "row_count": len(rows),
        },
    )


def _render_answer(template_id: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "按当前权限范围和查询条件没有匹配数据。[E1]"
    if template_id == "sales_summary":
        lines = [
            f"- {row['period']}：销售额 {row['total_amount']}，订单数 {row['order_count']}"
            for row in rows
        ]
        return "按当前权限范围的销售查询结果如下 [E1]：\n" + "\n".join(lines)
    if template_id == "top_products":
        lines = [
            (
                f"- {index}. 商品 {row['product_id']}：销售额 {row['total_amount']}，"
                f"销量 {row['total_quantity']}"
            )
            for index, row in enumerate(rows, start=1)
        ]
        return "按当前权限范围的畅销商品查询结果如下 [E1]：\n" + "\n".join(lines)
    if template_id == "inventory_balance":
        lines = [
            (
                f"- 商品 {row['product_id']}：在库 {row['quantity_on_hand']}，"
                f"在途 {row['quantity_in_transit']}"
            )
            for row in rows
        ]
        return "按当前权限范围的库存结余查询结果如下 [E1]：\n" + "\n".join(lines)
    return "查询完成 [E1]。"


def _clarify(message: str, code: str) -> SkillOutcome:
    return SkillOutcome(
        status=RunStatus.CLARIFY,
        answer=message,
        error_code=code,
    )
