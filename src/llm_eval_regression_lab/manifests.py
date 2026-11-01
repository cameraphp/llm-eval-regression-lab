"""Prompt and model-manifest loading with version and hash tracking (REQ-012, REQ-019)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import read_json, read_text_lf, sha256_canonical, sha256_text
from .retrieval import tokenize
from .schemas import (
    CITATION_FIELDS,
    DECISION_REFUSAL,
    REASON_CODES,
    SchemaError,
    is_semver,
)

TEST_DOUBLE_KIND = "rule_based_test_double"

# Fixture name -> model manifest path (relative to the project root).
FIXTURES: dict[str, str] = {
    "baseline": "model_manifests/deterministic-baseline-v1.json",
    "candidate": "model_manifests/deterministic-candidate-v2.json",
}

MODEL_FIELDS = {
    "behavior",
    "description",
    "documented_approved_changes",
    "documented_intentional_regressions",
    "is_ai_inference",
    "kind",
    "manifest_schema_version",
    "model_id",
    "model_version",
    "prompt",
}


class ManifestError(SchemaError):
    """Raised when a prompt or model manifest is invalid or its pins do not match."""


@dataclass(frozen=True)
class PromptInfo:
    prompt_id: str
    prompt_version: str
    sha256: str


@dataclass(frozen=True)
class RefusalRule:
    rule_id: str
    trigger_terms: tuple[str, ...]
    reason_code: str


@dataclass(frozen=True)
class AnswerRule:
    rule_id: str
    trigger_terms: tuple[str, ...]
    answer: str
    citations: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class ModelManifest:
    model_id: str
    model_version: str
    kind: str
    prompt: PromptInfo
    top_k: int
    refusal_rules: tuple[RefusalRule, ...]
    answer_rules: tuple[AnswerRule, ...]
    behavior_revision: str
    manifest_sha256: str
    documented_intentional_regressions: tuple[dict[str, str], ...]
    documented_approved_changes: tuple[dict[str, str], ...]

    def active_metadata(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_id": self.prompt.prompt_id,
            "prompt_version": self.prompt.prompt_version,
        }


def parse_front_matter(text: str) -> dict[str, str]:
    """Parse a minimal ``---``-delimited ``key: value`` front-matter block."""
    if not text.startswith("---\n"):
        raise ManifestError("prompt: missing front matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ManifestError("prompt: unterminated front matter")
    fields: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ManifestError(f"prompt: invalid front-matter line {line!r}")
        fields[key.strip()] = value.strip()
    return fields


def load_prompt(path: Path) -> PromptInfo:
    text = read_text_lf(path)
    fields = parse_front_matter(text)
    prompt_id = fields.get("prompt_id", "")
    prompt_version = fields.get("prompt_version", "")
    if not prompt_id or not is_semver(prompt_version):
        raise ManifestError("prompt: needs prompt_id and a semantic prompt_version")
    return PromptInfo(prompt_id=prompt_id, prompt_version=prompt_version, sha256=sha256_text(text))


def _terms(rule: dict[str, Any], where: str) -> tuple[str, ...]:
    terms = rule.get("trigger_terms")
    if not isinstance(terms, list) or not terms:
        raise ManifestError(f"{where}: 'trigger_terms' must be a non-empty list")
    for term in terms:
        if not isinstance(term, str) or tokenize(term) != [term]:
            raise ManifestError(f"{where}: trigger term {term!r} must be a single normalized token")
    return tuple(terms)


def behavior_revision(behavior: dict[str, Any]) -> str:
    return sha256_canonical(behavior)


def load_model_manifest(path: Path) -> ModelManifest:
    path = Path(path)
    try:
        obj = read_json(path)
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read model manifest: {exc}") from exc
    if not isinstance(obj, dict) or set(obj) != MODEL_FIELDS:
        raise ManifestError(f"model manifest: needs exactly {sorted(MODEL_FIELDS)}")
    if obj["kind"] != TEST_DOUBLE_KIND or obj["is_ai_inference"] is not False:
        raise ManifestError(
            f"model manifest: kind must be '{TEST_DOUBLE_KIND}' and is_ai_inference false"
        )
    if not isinstance(obj["model_id"], str) or not obj["model_id"].strip():
        raise ManifestError("model manifest: 'model_id' must be a non-empty string")
    for key in ("model_version", "manifest_schema_version"):
        if not is_semver(obj[key]):
            raise ManifestError(f"model manifest: '{key}' must be a semantic version")

    # Prompt pin
    pin = obj["prompt"]
    if not isinstance(pin, dict) or set(pin) != {"path", "prompt_id", "prompt_version", "sha256"}:
        raise ManifestError("model manifest.prompt: needs exactly path, prompt_id, "
                            "prompt_version, sha256")
    rel = PurePosixPath(pin["path"])
    if rel.is_absolute() or "\\" in pin["path"] or ":" in pin["path"]:
        raise ManifestError("model manifest.prompt: 'path' must be a relative POSIX path")
    prompt_path = path.parent.joinpath(*rel.parts)
    try:
        prompt = load_prompt(prompt_path)
    except OSError as exc:
        raise ManifestError(f"model manifest.prompt: cannot read prompt: {exc}") from exc
    if prompt.prompt_id != pin["prompt_id"] or prompt.prompt_version != pin["prompt_version"]:
        raise ManifestError("model manifest.prompt: prompt id/version does not match pin")
    if prompt.sha256 != pin["sha256"]:
        raise ManifestError(
            f"model manifest.prompt: sha256 mismatch (pin {pin['sha256']}, file {prompt.sha256})"
        )

    # Behavior block
    behavior = obj["behavior"]
    if not isinstance(behavior, dict) or set(behavior) != {
        "answer_rules",
        "refusal_rules",
        "retrieval",
    }:
        raise ManifestError("model manifest.behavior: needs answer_rules, refusal_rules, retrieval")
    retrieval = behavior["retrieval"]
    if (
        not isinstance(retrieval, dict)
        or retrieval.get("method") != "token_overlap"
        or set(retrieval) != {"method", "top_k"}
        or not isinstance(retrieval["top_k"], int)
        or isinstance(retrieval["top_k"], bool)
        or retrieval["top_k"] < 1
    ):
        raise ManifestError("model manifest.behavior.retrieval: token_overlap with top_k >= 1")

    rule_ids: set[str] = set()
    refusal_rules = []
    for index, rule in enumerate(behavior["refusal_rules"]):
        where = f"behavior.refusal_rules[{index}]"
        if not isinstance(rule, dict) or set(rule) != {"reason_code", "rule_id", "trigger_terms"}:
            raise ManifestError(f"{where}: needs exactly reason_code, rule_id, trigger_terms")
        if rule["reason_code"] not in REASON_CODES[DECISION_REFUSAL]:
            raise ManifestError(f"{where}: undocumented refusal reason code")
        refusal_rules.append(
            RefusalRule(rule["rule_id"], _terms(rule, where), rule["reason_code"])
        )
        rule_ids.add(rule["rule_id"])
    answer_rules = []
    for index, rule in enumerate(behavior["answer_rules"]):
        where = f"behavior.answer_rules[{index}]"
        if not isinstance(rule, dict) or set(rule) != {
            "answer",
            "citations",
            "rule_id",
            "trigger_terms",
        }:
            raise ManifestError(f"{where}: needs exactly answer, citations, rule_id, trigger_terms")
        citations = rule["citations"]
        if (
            not isinstance(rule["answer"], str)
            or not rule["answer"].strip()
            or not isinstance(citations, list)
            or not citations
            or not all(isinstance(c, dict) and set(c) == set(CITATION_FIELDS) for c in citations)
        ):
            raise ManifestError(f"{where}: needs answer text and well-formed citations")
        answer_rules.append(
            AnswerRule(
                rule["rule_id"],
                _terms(rule, where),
                rule["answer"],
                tuple(dict(c) for c in citations),
            )
        )
        rule_ids.add(rule["rule_id"])
    if len(rule_ids) != len(refusal_rules) + len(answer_rules):
        raise ManifestError("model manifest.behavior: duplicate rule_id")

    for key in ("documented_intentional_regressions", "documented_approved_changes"):
        notes = obj[key]
        if not isinstance(notes, list) or not all(
            isinstance(n, dict) and set(n) == {"case_id", "description", "rule_id"} for n in notes
        ):
            raise ManifestError(f"model manifest.{key}: entries need case_id, rule_id, description")

    return ModelManifest(
        model_id=obj["model_id"],
        model_version=obj["model_version"],
        kind=obj["kind"],
        prompt=prompt,
        top_k=retrieval["top_k"],
        refusal_rules=tuple(refusal_rules),
        answer_rules=tuple(answer_rules),
        behavior_revision=behavior_revision(behavior),
        manifest_sha256=sha256_canonical(obj),
        documented_intentional_regressions=tuple(obj["documented_intentional_regressions"]),
        documented_approved_changes=tuple(obj["documented_approved_changes"]),
    )


def fixture_manifest_path(root: Path, fixture: str) -> Path:
    if fixture not in FIXTURES:
        raise ManifestError(f"unknown fixture {fixture!r}; expected one of {sorted(FIXTURES)}")
    return Path(root).joinpath(*PurePosixPath(FIXTURES[fixture]).parts)
