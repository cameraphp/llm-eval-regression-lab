"""Canonical JSON, hashing, and text normalization helpers (NFR-001, NFR-005)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

_WHITESPACE = re.compile(r"\s+")


def canonical_json(obj: Any) -> str:
    """Serialize ``obj`` as canonical JSON: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def compact_canonical_json(obj: Any) -> str:
    """Single-line canonical JSON used for hashing and for simulator responses."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_canonical(obj: Any) -> str:
    """SHA-256 of the compact canonical JSON form of ``obj``."""
    return sha256_text(compact_canonical_json(obj))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_json_file(path: Path) -> str:
    """Hash a JSON file by content, independent of whitespace and key order."""
    return sha256_canonical(read_json(path))


def read_text_lf(path: Path) -> str:
    """Read a UTF-8 text file with line endings normalized to LF."""
    data = path.read_bytes().decode("utf-8")
    return data.replace("\r\n", "\n").replace("\r", "\n")


def sha256_text_file(path: Path) -> str:
    """Hash a text file as UTF-8 with LF line endings (CRLF checkouts hash identically)."""
    return sha256_text(read_text_lf(path))


def write_canonical_json(path: Path, obj: Any) -> bytes:
    """Write canonical JSON with UTF-8 encoding and LF newlines. Returns the bytes written."""
    data = canonical_json(obj).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def normalize_text(text: str) -> str:
    """Normalization for lexical matching: NFKC, lowercase, collapsed whitespace, trimmed."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).lower()).strip()
