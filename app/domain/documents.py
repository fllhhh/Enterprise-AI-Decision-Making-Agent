from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    doc_id: str
    title: str
    version: str
    effective_at: str
    source: str
    acl_departments: tuple[str, ...] = ()
    acl_roles: tuple[str, ...] = ()
    acl_public: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    chunk_id: str
    text: str
    metadata: DocumentMetadata
    locator: str

    def vector_metadata(self, *, is_active: bool = True) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "doc_id": self.metadata.doc_id,
            "title": self.metadata.title,
            "version": self.metadata.version,
            "effective_at": self.metadata.effective_at,
            "effective_ts": _effective_timestamp(self.metadata.effective_at),
            "source": self.metadata.source,
            "locator": self.locator,
            "is_active": is_active,
            "acl_public": self.metadata.acl_public,
        }
        for department in self.metadata.acl_departments:
            metadata[_acl_key("department", department)] = True
        for role in self.metadata.acl_roles:
            metadata[_acl_key("role", role)] = True
        metadata.update(self.metadata.extra)
        return metadata


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float


def _acl_key(kind: str, value: str) -> str:
    normalized = "".join(character if character.isalnum() else "_" for character in value.lower())
    return f"acl_{kind}_{normalized}"


def _effective_timestamp(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed.timestamp()
    except ValueError:
        return 0.0
