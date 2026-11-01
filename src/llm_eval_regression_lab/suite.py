"""Versioned case-manifest loading with hash and change-log integrity (REQ-002)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import read_json, sha256_canonical
from .corpus import Corpus, load_corpus
from .schemas import Case, SchemaError, is_semver, parse_case

MANIFEST_FIELDS = {"change_log", "corpus", "description", "cases", "suite_id", "suite_version",
                   "synthetic"}
ENTRY_FIELDS = {"case_id", "case_version", "path", "sha256", "status"}
CHANGE_FIELDS = {"case_id", "case_version", "change", "reason"}
STATUSES = ("active", "superseded")
CHANGE_KINDS = ("added", "expectation_changed")


class SuiteIntegrityError(SchemaError):
    """Raised when the case manifest, a case file, or the corpus reference fails integrity."""


@dataclass(frozen=True)
class SuiteCase:
    case: Case
    path: str  # POSIX path relative to the manifest directory
    sha256: str


@dataclass(frozen=True)
class Suite:
    suite_id: str
    suite_version: str
    manifest_sha256: str
    corpus: Corpus
    cases: tuple[SuiteCase, ...]  # active cases only, sorted by case_id


def _relative_path(base: Path, rel: Any, where: str) -> Path:
    if not isinstance(rel, str) or not rel.strip():
        raise SuiteIntegrityError(f"{where}: 'path' must be a non-empty string")
    posix = PurePosixPath(rel)
    if posix.is_absolute() or "\\" in rel or ":" in rel:
        raise SuiteIntegrityError(f"{where}: 'path' must be a relative POSIX path")
    return base.joinpath(*posix.parts)


def load_suite(manifest_path: Path) -> Suite:
    manifest_path = Path(manifest_path)
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        raise SuiteIntegrityError(f"cannot read suite manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SuiteIntegrityError("manifest: must be a JSON object")
    missing = sorted(MANIFEST_FIELDS - set(manifest))
    extra = sorted(set(manifest) - MANIFEST_FIELDS)
    if missing or extra:
        raise SuiteIntegrityError(f"manifest: missing {missing} / unknown {extra} fields")
    if manifest["synthetic"] is not True:
        raise SuiteIntegrityError("manifest: suite must be declared synthetic")
    if not is_semver(manifest["suite_version"]):
        raise SuiteIntegrityError("manifest: 'suite_version' must be a semantic version")
    base = manifest_path.parent

    # Corpus reference
    ref = manifest["corpus"]
    if not isinstance(ref, dict) or set(ref) != {"corpus_version", "path", "sha256"}:
        raise SuiteIntegrityError("manifest.corpus: needs exactly path, corpus_version, sha256")
    corpus_path = _relative_path(base, ref["path"], "manifest.corpus")
    try:
        corpus = load_corpus(corpus_path)
    except OSError as exc:
        raise SuiteIntegrityError(f"manifest.corpus: cannot read corpus: {exc}") from exc
    if corpus.corpus_version != ref["corpus_version"]:
        raise SuiteIntegrityError("manifest.corpus: corpus_version does not match corpus file")
    if corpus.sha256 != ref["sha256"]:
        raise SuiteIntegrityError(
            f"manifest.corpus: sha256 mismatch (manifest {ref['sha256']}, file {corpus.sha256})"
        )

    # Change log
    change_log = manifest["change_log"]
    if not isinstance(change_log, list):
        raise SuiteIntegrityError("manifest.change_log: must be a list")
    logged: set[tuple[str, str]] = set()
    for index, change in enumerate(change_log):
        where = f"manifest.change_log[{index}]"
        if not isinstance(change, dict) or set(change) != CHANGE_FIELDS:
            raise SuiteIntegrityError(f"{where}: needs exactly {sorted(CHANGE_FIELDS)}")
        if change["change"] not in CHANGE_KINDS:
            raise SuiteIntegrityError(f"{where}: 'change' must be one of {CHANGE_KINDS}")
        if not isinstance(change["reason"], str) or not change["reason"].strip():
            raise SuiteIntegrityError(f"{where}: 'reason' must be a non-empty string")
        logged.add((change["case_id"], change["case_version"]))

    # Case entries
    entries = manifest["cases"]
    if not isinstance(entries, list) or not entries:
        raise SuiteIntegrityError("manifest.cases: must be a non-empty list")
    seen: set[tuple[str, str]] = set()
    active: dict[str, SuiteCase] = {}
    for index, entry in enumerate(entries):
        where = f"manifest.cases[{index}]"
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise SuiteIntegrityError(f"{where}: needs exactly {sorted(ENTRY_FIELDS)}")
        key = (entry["case_id"], entry["case_version"])
        if key in seen:
            raise SuiteIntegrityError(f"{where}: duplicate case version {key}")
        seen.add(key)
        if entry["status"] not in STATUSES:
            raise SuiteIntegrityError(f"{where}: 'status' must be one of {STATUSES}")
        if key not in logged:
            raise SuiteIntegrityError(f"{where}: no change_log entry for {key}")
        case_path = _relative_path(base, entry["path"], where)
        if not case_path.is_file():
            raise SuiteIntegrityError(
                f"{where}: case file {entry['path']} is missing (historical files must be kept)"
            )
        try:
            raw_case = read_json(case_path)
        except ValueError as exc:
            raise SuiteIntegrityError(f"{where}: case file is not valid JSON: {exc}") from exc
        actual_sha = sha256_canonical(raw_case)
        if actual_sha != entry["sha256"]:
            raise SuiteIntegrityError(
                f"{where}: sha256 mismatch for {entry['path']} - expectations changed without "
                f"a version bump (manifest {entry['sha256']}, file {actual_sha})"
            )
        case = parse_case(raw_case)
        if (case.case_id, case.case_version) != key:
            raise SuiteIntegrityError(f"{where}: case file id/version does not match entry")
        unknown_docs = sorted(set(case.retrieval_scope) - set(corpus.documents))
        if unknown_docs:
            raise SuiteIntegrityError(f"{where}: retrieval_scope has unknown documents")
        if entry["status"] == "active":
            if case.case_id in active:
                raise SuiteIntegrityError(f"{where}: more than one active version of {key[0]}")
            if case.suite_version != manifest["suite_version"]:
                raise SuiteIntegrityError(f"{where}: active case suite_version mismatch")
            active[case.case_id] = SuiteCase(case=case, path=entry["path"], sha256=actual_sha)

    orphan_logs = sorted(logged - seen)
    if orphan_logs:
        raise SuiteIntegrityError(f"manifest.change_log: entries without cases {orphan_logs}")

    return Suite(
        suite_id=manifest["suite_id"],
        suite_version=manifest["suite_version"],
        manifest_sha256=sha256_canonical(manifest),
        corpus=corpus,
        cases=tuple(active[case_id] for case_id in sorted(active)),
    )
