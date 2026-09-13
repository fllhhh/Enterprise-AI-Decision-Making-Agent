from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArgumentType(StrEnum):
    DATE = "date"
    INTEGER = "integer"


@dataclass(frozen=True, slots=True)
class TemplateArgument:
    name: str
    argument_type: ArgumentType
    required: bool
    description: str
    default: str | int | None = None


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    template_id: str
    title: str
    description: str
    sql: str
    arguments: tuple[TemplateArgument, ...]
    max_rows: int = 200
    timeout_seconds: float = 3.0

    def prompt_description(self) -> str:
        arguments = ", ".join(
            f"{argument.name}({argument.argument_type.value}"
            f"{', required' if argument.required else ', optional'})"
            for argument in self.arguments
        )
        return (
            f"{self.template_id}: {self.description}; arguments: {arguments or 'none'}"
        )

