"""Human-readable summaries and the benchmark-evidence vs production-non-claims text (SAFE-005)."""

from __future__ import annotations

from typing import Any

NON_CLAIMS = (
    "This project evaluates deterministic fixtures against a small synthetic benchmark. Results "
    "demonstrate that the included checks execute as designed for these fixtures only. They do "
    "not establish real LLM, RAG, safety, groundedness, or production performance. The baseline "
    "and candidate are rule-based test doubles, not AI models; groundedness is a lexical, "
    "fixture-bound proportion, not semantic entailment or factuality."
)


def render_run_summary(artifact: dict[str, Any]) -> str:
    summary = artifact["summary"]
    model = artifact["model"]
    prompt = artifact["prompt"]
    lines = [
        f"Run: fixture={artifact['fixture']} suite={artifact['suite']['suite_id']}@"
        f"{artifact['suite']['suite_version']} corpus={artifact['corpus']['corpus_version']}",
        f"  model={model['model_id']}@{model['model_version']} ({model['kind']}, "
        f"behavior_revision={model['behavior_revision'][:12]})",
        f"  prompt={prompt['prompt_id']}@{prompt['prompt_version']} "
        f"(sha256={prompt['sha256'][:12]}) evaluator={artifact['evaluator_version']}",
        "",
        f"  {'case_id':<30} {'mode':<17} {'status':<17} {'grounded':>8}  failure_codes",
    ]
    for case in artifact["cases"]:
        grounded = "-" if case["groundedness"] is None else f"{case['groundedness']:.4f}"
        codes = ", ".join(case["failure_codes"]) or "-"
        lines.append(
            f"  {case['case_id']:<30} {case['mode']:<17} {case['status']:<17} {grounded:>8}  "
            f"{codes}"
        )
    lines += [
        "",
        f"  behavior cases: {summary['behavior_passed']}/{summary['behavior_cases']} passed; "
        f"negative controls: {summary['controls_detected']}/{summary['negative_controls']} "
        "detected",
        f"  RUN RESULT: {'PASS' if summary['run_passed'] else 'FAIL'}",
        "",
        f"NOTE: {NON_CLAIMS}",
    ]
    return "\n".join(lines) + "\n"


def render_comparison(report: dict[str, Any]) -> str:
    gate = report["gate"]
    lines = [
        "# Baseline vs candidate comparison",
        "",
        f"- Baseline: `{report['baseline']['fixture']}` "
        f"({report['baseline']['model_id']}@{report['baseline']['model_version']}, prompt "
        f"{report['baseline']['prompt_version']})",
        f"- Candidate: `{report['candidate']['fixture']}` "
        f"({report['candidate']['model_id']}@{report['candidate']['model_version']}, prompt "
        f"{report['candidate']['prompt_version']})",
        f"- Mode: {'strict' if report['strict'] else 'default'}; blocking classifications: "
        f"{', '.join(gate['blocking_classifications'])}",
        "",
        "| case_id | classification | baseline | candidate | approved | reasons |",
        "|---|---|---|---|---|---|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['classification']} | {case['baseline_status']} | "
            f"{case['candidate_status']} | {'yes' if case['approved'] else 'no'} | "
            f"{'; '.join(case['reasons'])} |"
        )
    counts = report["counts"]
    lines += [
        "",
        "Counts: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)),
    ]
    if report["unused_approvals"]:
        lines.append(f"Unused approvals (stale, review): {', '.join(report['unused_approvals'])}")
    lines += [
        "",
        f"**GATE: {gate['result'].upper()}**"
        + (
            f" - blocking cases: {', '.join(gate['blocking_cases'])}"
            if gate["blocking_cases"]
            else ""
        ),
        "",
        f"> {NON_CLAIMS}",
    ]
    return "\n".join(lines) + "\n"
