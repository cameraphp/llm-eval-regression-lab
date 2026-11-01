"""Synthetic corpus loading and validation (REQ-001, SAFE-004)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import read_json, sha256_canonical
from .schemas import SchemaError

DOCUMENT_FIELDS = {
    "allowed_for_benchmark",
    "content",
    "corpus_version",
    "document_id",
    "synthetic",
    "title",
}
CORPUS_FIELDS = {"corpus_version", "description", "documents", "synthetic"}


@dataclass(frozen=True)
class Document:
    document_id: str
    corpus_version: str
    title: str
    content: str


@dataclass(frozen=True)
class Corpus:
    corpus_version: str
    sha256: str
    documents: dict[str, Document]

    def get(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.documents))


def validate_corpus_dict(obj: Any) -> Corpus:
    if not isinstance(obj, dict):
        raise SchemaError("corpus: must be a JSON object")
    missing = sorted(CORPUS_FIELDS - set(obj))
    extra = sorted(set(obj) - CORPUS_FIELDS)
    if missing or extra:
        raise SchemaError(f"corpus: missing {missing} / unknown {extra} fields")
    version = obj["corpus_version"]
    if not isinstance(version, str) or not version.strip():
        raise SchemaError("corpus: 'corpus_version' must be a non-empty string")
    if obj["synthetic"] is not True:
        raise SchemaError("corpus: must be declared synthetic")
    if not isinstance(obj["documents"], list) or not obj["documents"]:
        raise SchemaError("corpus: 'documents' must be a non-empty list")

    documents: dict[str, Document] = {}
    for index, doc in enumerate(obj["documents"]):
        where = f"corpus.documents[{index}]"
        if not isinstance(doc, dict):
            raise SchemaError(f"{where}: must be a JSON object")
        missing = sorted(DOCUMENT_FIELDS - set(doc))
        extra = sorted(set(doc) - DOCUMENT_FIELDS)
        if missing or extra:
            raise SchemaError(f"{where}: missing {missing} / unknown {extra} fields")
        for key in ("document_id", "corpus_version", "title", "content"):
            if not isinstance(doc[key], str) or not doc[key].strip():
                raise SchemaError(f"{where}: '{key}' must be a non-empty string")
        if doc["synthetic"] is not True or doc["allowed_for_benchmark"] is not True:
            raise SchemaError(
                f"{where}: document must be synthetic and allowed_for_benchmark"
            )
        if doc["corpus_version"] != version:
            raise SchemaError(f"{where}: corpus_version does not match corpus '{version}'")
        if doc["document_id"] in documents:
            raise SchemaError(f"{where}: duplicate document_id {doc['document_id']}")
        documents[doc["document_id"]] = Document(
            document_id=doc["document_id"],
            corpus_version=doc["corpus_version"],
            title=doc["title"],
            content=doc["content"],
        )
    return Corpus(
        corpus_version=version,
        sha256=sha256_canonical(obj),
        documents=dict(sorted(documents.items())),
    )


def load_corpus(path: Path) -> Corpus:
    return validate_corpus_dict(read_json(path))
