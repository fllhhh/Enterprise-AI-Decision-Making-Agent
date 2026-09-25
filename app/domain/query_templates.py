"""白名单参数化数据查询的类型契约。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

StatementBuilder = Callable[[Mapping[str, Any]], Any]


class ArgumentType(StrEnum):
    """参数校验器支持的参数类型。"""

    DATE = "date"
    INTEGER = "integer"


@dataclass(frozen=True, slots=True)
class TemplateArgument:
    """查询模板接受的单个参数。"""

    name: str
    argument_type: ArgumentType
    required: bool
    description: str
    default: str | int | None = None


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    """经过审核的 ORM 查询及其执行约束。

    查询由服务端 ``statement_builder`` 构建。LLM 只能收到模板 ID、
    描述和参数元数据，不会收到 ORM 表达式或 SQL 文本。
    """

    template_id: str
    title: str
    description: str
    statement_builder: StatementBuilder
    arguments: tuple[TemplateArgument, ...]
    view_name: str = ""
    max_rows: int = 200
    timeout_seconds: float = 3.0

    def prompt_description(self) -> str:
        """生成可安全放入 LLM Prompt 的能力描述。"""
        arguments = ", ".join(
            f"{argument.name}({argument.argument_type.value}"
            f"{', required' if argument.required else ', optional'})"
            for argument in self.arguments
        )
        return (
            f"{self.template_id}: {self.description}; arguments: {arguments or 'none'}"
        )
