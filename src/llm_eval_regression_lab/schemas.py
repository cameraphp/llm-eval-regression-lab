"""Data contracts, controlled vocabularies, and structured-response validation.

Requirements: REQ-003 (case contract), REQ-004 (response schema), REQ-005 (decision invariants).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

DECISION_ANSWER = "answer"
DECISION_INSUFFICIENT = "insufficient_evidence"
DECISION_REFUSAL = "refusal"
DECISIONS = (DECISION_ANSWER, DECISION_INSUFFICIENT, DECISION_REFUSAL)

# Controlled reason codes per non-answer decision, each with exactly one allowed message.
REASON_CODES: dict[str, tuple[str, ...]] = {
    DECISION_INSUFFICIENT: ("EVIDENCE_NOT_FOUND", "NO_RETRIEVED_CONTEXT"),
    DECISION_REFUSAL: ("POLICY_RESTRICTED_CREDENTIAL_REQUEST",),
}
CONTROLLED_MESSAGES: dict[str, str] = {
    "NO_RETRIEVED_CONTEXT": "No context documents were retrieved for this request.",
    "EVIDENCE_NOT_FOUND": "The retrieved synthetic documents do not establish an answer.",
    "POLICY_RESTRICTED_CREDENTIAL_REQUEST": (
        "This request asks for restricted credential information and is refused."
    ),
}

# Evaluator failure codes (see requirements.md REQ-004..REQ-012).
FAILURE_CODES = (
    "ANSWER_FORBIDDEN_FRAGMENT",
    "ANSWER_FRAGMENT_MISSING",
    "ANSWER_SENTENCE_UNSUPPORTED",
    "CASE_ID_MISMATCH",
    "CITATION_OUT_OF_SCOPE",
    "CITATION_QUOTE_NOT_FOUND",
    "CITATION_REQUIRED_MISSING",
    "CITATION_UNKNOWN_DOCUMENT",
    "CLAIM_UNSUPPORTED",
    "DECISION_INVARIANT_VIOLATION",
    "DECISION_MISMATCH",
    "GROUNDEDNESS_BELOW_MIN",
    "METADATA_MISMATCH",
    "REASON_CODE_MISMATCH",
    "SCHEMA_INVALID",
    "UNSUPPORTED_ANSWER_LEAKAGE",
)

RESPONSE_FIELDS = (
    "answer",
    "case_id",
    "citations",
    "decision",
    "message",
    "model_id",
    "model_version",
    "prompt_id",
    "prompt_version",
    "reason_code",
)
METADATA_FIELDS = ("model_id", "model_version", "prompt_id", "prompt_version")
CITATION_FIELDS = ("document_id", "supporting_quote")
ACTIVE_PLACEHOLDER = "<<ACTIVE>>"

CASE_MODES = ("behavior", "negative_control")
CASE_FIELDS = {
    "case_id",
    "case_version",
    "category",
    "expected",
    "input",
    "mode",
    "retrieval_scope",
    "suite_version",
    "synthetic_fixture_note",
}
EXPECTED_FIELDS = {
    "claims",
    "decision",
    "forbidden_answer_fragments",
    "min_groundedness",
    "reason_code",
    "required_answer_fragments",
    "required_citations",
}
NEGATIVE_CONTROL_FIELDS = {"expected_failure_codes", "injected_raw", "injected_response"}


class SchemaError(ValueError):
    """Raised when an input fixture (corpus, case, manifest) violates its contract."""


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str


@dataclass(frozen=True)
class Claim:
    claim_id: str
    fragment: str
    support_document_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedBehavior:
    decision: str
    reason_code: str | None
    required_answer_fragments: tuple[str, ...]
    forbidden_answer_fragments: tuple[str, ...]
    required_citations: tuple[str, ...]
    claims: tuple[Claim, ...]
    min_groundedness: float | None


@dataclass(frozen=True)
class NegativeControl:
    injected_response: dict[str, Any] | None
    injected_raw: str | None
    expected_failure_codes: tuple[str, ...]


@dataclass(frozen=True)
class Case:
    case_id: str
    case_version: str
    suite_version: str
    category: str
    mode: str
    synthetic_fixture_note: str
    question: str
    retrieval_scope: tuple[str, ...]
    expected: ExpectedBehavior
    negative_control: NegativeControl | None


# --------------------------------------------------------------------------------------------
# Small typed accessors
# --------------------------------------------------------------------------------------------


def _require_str(obj: dict[str, Any], key: str, where: str, *, allow_empty: bool = False) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SchemaError(f"{where}: '{key}' must be a non-empty string")
    return value


def _require_str_list(obj: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = obj.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise SchemaError(f"{where}: '{key}' must be a list of non-empty strings")
    if len(set(value)) != len(value):
        raise SchemaError(f"{where}: '{key}' contains duplicates")
    return tuple(value)


def _require_exact_keys(obj: Any, keys: set[str], where: str, optional: set[str] = frozenset()):
    if not isinstance(obj, dict):
        raise SchemaError(f"{where}: must be a JSON object")
    missing = sorted(keys - set(obj))
    extra = sorted(set(obj) - keys - optional)
    if missing:
        raise SchemaError(f"{where}: missing fields {missing}")
    if extra:
        raise SchemaError(f"{where}: unknown fields {extra}")


def is_semver(value: Any) -> bool:
    return isinstance(value, str) and bool(SEMVER.match(value))


# --------------------------------------------------------------------------------------------
# Case contract (REQ-003)
# --------------------------------------------------------------------------------------------


def parse_case(obj: Any) -> Case:
    """Validate a case document and return an immutable :class:`Case`."""
    where = f"case {obj.get('case_id', '?') if isinstance(obj, dict) else '?'}"
    _require_exact_keys(obj, CASE_FIELDS, where, optional={"negative_control"})
    case_id = _require_str(obj, "case_id", where)
    for key in ("case_version", "suite_version"):
        if not is_semver(obj.get(key)):
            raise SchemaError(f"{where}: '{key}' must be a semantic version")
    category = _require_str(obj, "category", where)
    mode = obj.get("mode")
    if mode not in CASE_MODES:
        raise SchemaError(f"{where}: 'mode' must be one of {CASE_MODES}")
    note = _require_str(obj, "synthetic_fixture_note", where)
    if "synthetic" not in note.lower():
        raise SchemaError(f"{where}: 'synthetic_fixture_note' must state the fixture is synthetic")
    _require_exact_keys(obj["input"], {"question"}, f"{where}.input")
    question = _require_str(obj["input"], "question", f"{where}.input")
    scope = _require_str_list(obj, "retrieval_scope", where)

    expected = _parse_expected(obj["expected"], f"{where}.expected")

    negative_control = None
    if mode == "negative_control":
        if "negative_control" not in obj:
            raise SchemaError(f"{where}: negative_control mode requires 'negative_control'")
        negative_control = _parse_negative_control(obj["negative_control"], f"{where}.nc")
    elif "negative_control" in obj:
        raise SchemaError(f"{where}: 'negative_control' is only allowed in negative_control mode")

    return Case(
        case_id=case_id,
        case_version=obj["case_version"],
        suite_version=obj["suite_version"],
        category=category,
        mode=mode,
        synthetic_fixture_note=note,
        question=question,
        retrieval_scope=scope,
        expected=expected,
        negative_control=negative_control,
    )


def _parse_expected(obj: Any, where: str) -> ExpectedBehavior:
    _require_exact_keys(obj, EXPECTED_FIELDS, where)
    decision = obj["decision"]
    if decision not in DECISIONS:
        raise SchemaError(f"{where}: 'decision' must be one of {DECISIONS}")
    claims_raw = obj["claims"]
    if not isinstance(claims_raw, list):
        raise SchemaError(f"{where}: 'claims' must be a list")
    claims = []
    for index, claim in enumerate(claims_raw):
        cwhere = f"{where}.claims[{index}]"
        _require_exact_keys(claim, {"claim_id", "fragment", "support_document_ids"}, cwhere)
        support = _require_str_list(claim, "support_document_ids", cwhere)
        if not support:
            raise SchemaError(f"{cwhere}: 'support_document_ids' must not be empty")
        claims.append(
            Claim(
                claim_id=_require_str(claim, "claim_id", cwhere),
                fragment=_require_str(claim, "fragment", cwhere),
                support_document_ids=support,
            )
        )
    if len({c.claim_id for c in claims}) != len(claims):
        raise SchemaError(f"{where}: duplicate claim_id")
    required_citations = _require_str_list(obj, "required_citations", where)
    reason_code = obj["reason_code"]
    min_groundedness = obj["min_groundedness"]

    if decision == DECISION_ANSWER:
        if reason_code is not None:
            raise SchemaError(f"{where}: answer expectations must have reason_code null")
        if not claims or not required_citations:
            raise SchemaError(f"{where}: answer expectations need claims and required_citations")
        if (
            isinstance(min_groundedness, bool)
            or not isinstance(min_groundedness, (int, float))
            or not 0.0 <= float(min_groundedness) <= 1.0
        ):
            raise SchemaError(f"{where}: 'min_groundedness' must be a number in [0, 1]")
        min_groundedness = float(min_groundedness)
    else:
        if reason_code not in REASON_CODES[decision]:
            raise SchemaError(f"{where}: reason_code must be one of {REASON_CODES[decision]}")
        if claims or required_citations or min_groundedness is not None:
            raise SchemaError(
                f"{where}: non-answer expectations must have no claims/citations and "
                "min_groundedness null"
            )

    return ExpectedBehavior(
        decision=decision,
        reason_code=reason_code,
        required_answer_fragments=_require_str_list(obj, "required_answer_fragments", where),
        forbidden_answer_fragments=_require_str_list(obj, "forbidden_answer_fragments", where),
        required_citations=required_citations,
        claims=tuple(claims),
        min_groundedness=min_groundedness,
    )


def _parse_negative_control(obj: Any, where: str) -> NegativeControl:
    if not isinstance(obj, dict):
        raise SchemaError(f"{where}: must be a JSON object")
    extra = sorted(set(obj) - NEGATIVE_CONTROL_FIELDS)
    if extra:
        raise SchemaError(f"{where}: unknown fields {extra}")
    has_response = "injected_response" in obj
    has_raw = "injected_raw" in obj
    if has_response == has_raw:
        raise SchemaError(f"{where}: exactly one of injected_response / injected_raw is required")
    if has_response and not isinstance(obj["injected_response"], dict):
        raise SchemaError(f"{where}: 'injected_response' must be an object")
    if has_raw and not isinstance(obj["injected_raw"], str):
        raise SchemaError(f"{where}: 'injected_raw' must be a string")
    codes = _require_str_list(obj, "expected_failure_codes", where)
    if not codes:
        raise SchemaError(f"{where}: 'expected_failure_codes' must not be empty")
    unknown = sorted(set(codes) - set(FAILURE_CODES))
    if unknown:
        raise SchemaError(f"{where}: unknown failure codes {unknown}")
    return NegativeControl(
        injected_response=obj.get("injected_response"),
        injected_raw=obj.get("injected_raw"),
        expected_failure_codes=tuple(sorted(codes)),
    )


# --------------------------------------------------------------------------------------------
# Structured response (REQ-004, REQ-005)
# --------------------------------------------------------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def parse_response(raw: str) -> tuple[dict[str, Any] | None, list[Finding]]:
    """Parse a raw response string. Returns (object, []) or (None, [SCHEMA_INVALID])."""
    try:
        obj = json.loads(
            raw, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant
        )
    except (ValueError, TypeError) as exc:
        return None, [Finding("SCHEMA_INVALID", f"response is not valid JSON: {exc}")]
    if not isinstance(obj, dict):
        return None, [Finding("SCHEMA_INVALID", "response must be a JSON object")]
    return obj, []


def _structural_errors(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(set(RESPONSE_FIELDS) - set(obj))
    extra = sorted(set(obj) - set(RESPONSE_FIELDS))
    if missing:
        errors.append(f"missing fields {missing}")
    if extra:
        errors.append(f"unknown fields {extra}")
    if errors:
        return errors

    for key in ("case_id", "prompt_id", "model_id"):
        if not isinstance(obj[key], str) or not obj[key].strip():
            errors.append(f"'{key}' must be a non-empty string")
    for key in ("prompt_version", "model_version"):
        if not is_semver(obj[key]):
            errors.append(f"'{key}' must be a semantic version")
    if obj["decision"] not in DECISIONS:
        errors.append(f"'decision' must be one of {list(DECISIONS)}")
    for key in ("answer", "reason_code", "message"):
        if obj[key] is not None and not isinstance(obj[key], str):
            errors.append(f"'{key}' must be a string or null")
    citations = obj["citations"]
    if not isinstance(citations, list):
        errors.append("'citations' must be a list")
    else:
        for index, citation in enumerate(citations):
            if not isinstance(citation, dict) or set(citation) != set(CITATION_FIELDS):
                errors.append(f"citations[{index}] must have exactly {list(CITATION_FIELDS)}")
                continue
            for key in CITATION_FIELDS:
                if not isinstance(citation[key], str) or not citation[key].strip():
                    errors.append(f"citations[{index}].{key} must be a non-empty string")
    return errors


def validate_response(obj: dict[str, Any]) -> list[Finding]:
    """Validate structure, then decision-specific invariants. Returns findings (empty = valid).

    Structural problems return only ``SCHEMA_INVALID`` findings, because invariants cannot be
    evaluated reliably on a structurally invalid object.
    """
    structural = _structural_errors(obj)
    if structural:
        return [Finding("SCHEMA_INVALID", error) for error in structural]

    findings: list[Finding] = []
    decision = obj["decision"]
    if decision == DECISION_ANSWER:
        if obj["answer"] is None or not obj["answer"].strip():
            findings.append(
                Finding("DECISION_INVARIANT_VIOLATION", "answer decision requires answer text")
            )
        if not obj["citations"]:
            findings.append(
                Finding("DECISION_INVARIANT_VIOLATION", "answer decision requires a citation")
            )
        if obj["reason_code"] is not None or obj["message"] is not None:
            findings.append(
                Finding(
                    "DECISION_INVARIANT_VIOLATION",
                    "answer decision requires reason_code and message to be null",
                )
            )
    else:
        if obj["answer"] is not None or obj["citations"]:
            findings.append(
                Finding(
                    "UNSUPPORTED_ANSWER_LEAKAGE",
                    f"{decision} must not carry answer text or citations",
                )
            )
        reason = obj["reason_code"]
        if reason not in REASON_CODES[decision]:
            findings.append(
                Finding(
                    "DECISION_INVARIANT_VIOLATION",
                    f"{decision} requires reason_code in {list(REASON_CODES[decision])}",
                )
            )
        elif obj["message"] != CONTROLLED_MESSAGES[reason]:
            findings.append(
                Finding(
                    "DECISION_INVARIANT_VIOLATION",
                    f"message must be the controlled text for {reason}",
                )
            )
    return findings
