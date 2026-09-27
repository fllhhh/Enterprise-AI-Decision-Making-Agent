"""无外部依赖的轻量 Prometheus 文本指标。"""

from __future__ import annotations

from collections import Counter, defaultdict
from threading import Lock


class RuntimeMetrics:
    def __init__(self) -> None:
        self._counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
        self._duration_sum: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._lock = Lock()

    def increment(self, name: str, **labels: str) -> None:
        key = (name, tuple(sorted((key, str(value)) for key, value in labels.items())))
        with self._lock:
            self._counters[key] += 1

    def observe_seconds(self, name: str, value: float, **labels: str) -> None:
        label_tuple = tuple(sorted((key, str(item)) for key, item in labels.items()))
        with self._lock:
            self._duration_sum[(name + "_sum", label_tuple)] += value
            self._counters[(name + "_count", label_tuple)] += 1

    def render(self) -> str:
        lines = ["# enterprise_agent v0.3 runtime metrics"]
        with self._lock:
            values = {**self._duration_sum, **self._counters}
            for (name, labels), value in sorted(values.items()):
                suffix = ""
                if labels:
                    suffix = "{" + ",".join(f'{key}="{val}"' for key, val in labels) + "}"
                lines.append(f"enterprise_agent_{name}{suffix} {value}")
        return "\n".join(lines) + "\n"
