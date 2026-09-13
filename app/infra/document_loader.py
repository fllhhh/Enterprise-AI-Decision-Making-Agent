from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.domain.documents import DocumentChunk, DocumentMetadata
from app.domain.errors import ConfigurationError


class DocumentLoader:
    def __init__(self, *, chunk_size: int = 600, chunk_overlap: int = 100) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load(self, path: Path) -> list[DocumentChunk]:
        catalog_path = path / "catalog.json"
        if not catalog_path.exists():
            raise ConfigurationError(f"演示文档目录缺少 catalog.json: {path}")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        chunks: list[DocumentChunk] = []
        for filename, raw_metadata in catalog.items():
            document_path = path / filename
            if not document_path.exists():
                raise ConfigurationError(f"catalog.json 引用的文档不存在: {filename}")
            metadata = _metadata_from_dict(filename, raw_metadata)
            if document_path.suffix.lower() == ".pdf":
                sections = _load_pdf_sections(document_path)
            else:
                sections = _load_text_sections(document_path)
            for section_title, section_text in sections:
                for index, text in enumerate(
                    _chunk_text(
                        section_text,
                        chunk_size=self.chunk_size,
                        overlap=self.chunk_overlap,
                    )
                ):
                    locator = f"section={section_title};chunk={index + 1}"
                    chunk_id = _chunk_id(metadata.doc_id, metadata.version, locator)
                    chunks.append(
                        DocumentChunk(
                            chunk_id=chunk_id,
                            text=text,
                            metadata=metadata,
                            locator=locator,
                        )
                    )
        return chunks


def _metadata_from_dict(filename: str, value: dict) -> DocumentMetadata:
    required = {"doc_id", "title", "version", "effective_at"}
    missing = required.difference(value)
    if missing:
        raise ConfigurationError(
            f"{filename} 缺少元数据字段: {', '.join(sorted(missing))}"
        )
    known = {
        "doc_id",
        "title",
        "version",
        "effective_at",
        "source",
        "acl_departments",
        "acl_roles",
        "acl_public",
    }
    return DocumentMetadata(
        doc_id=str(value["doc_id"]),
        title=str(value["title"]),
        version=str(value["version"]),
        effective_at=str(value["effective_at"]),
        source=str(value.get("source", filename)),
        acl_departments=tuple(value.get("acl_departments", [])),
        acl_roles=tuple(value.get("acl_roles", [])),
        acl_public=bool(value.get("acl_public", False)),
        extra={key: item for key, item in value.items() if key not in known},
    )


def _load_text_sections(path: Path) -> list[tuple[str, str]]:
    content = path.read_text(encoding="utf-8").strip()
    matches = list(re.finditer(r"^#{1,6}\s+(.+)$", content, flags=re.MULTILINE))
    if not matches:
        return [(path.stem, content)]
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if body:
            sections.append((match.group(1).strip(), body))
    return sections


def _load_pdf_sections(path: Path) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ConfigurationError(
            "解析 PDF 需要安装 RAG 依赖，请执行 pip install -e '.[rag]'"
        ) from exc
    reader = PdfReader(str(path))
    sections: list[tuple[str, str]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            sections.append((f"page-{page_number}", text.strip()))
    return sections


def _chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            preferred_break = max(
                normalized.rfind("\n", start, end),
                normalized.rfind("。", start, end),
                normalized.rfind("；", start, end),
            )
            if preferred_break > start + chunk_size // 2:
                end = preferred_break + 1
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _chunk_id(doc_id: str, version: str, locator: str) -> str:
    raw = f"{doc_id}:{version}:{locator}".encode()
    return hashlib.sha1(raw).hexdigest()

