"""Offline end-to-end demonstration (REQ-018, SAFE-006).

Steps (all through the real CLI, in subprocesses, with no network):

1. validate the suite manifest;
2. run the baseline twice -> both runs must be byte-identical to each other and to the golden file;
3. run the candidate;
4. strict comparison golden vs candidate -> MUST exit 1 with exactly the documented intentional
   regressions.

The candidate comparison is reported as an expected demonstration of a FAILED comparison, never
as a pass. This script exits 0 only if every expectation holds; otherwise it prints
``DEMO EXPECTATION FAILED`` and exits 1.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_eval_regression_lab.canonical import read_json  # noqa: E402
from llm_eval_regression_lab.manifests import (  # noqa: E402
    fixture_manifest_path,
    load_model_manifest,
)
from llm_eval_regression_lab.offline import enforce_offline  # noqa: E402
from llm_eval_regression_lab.reporting import NON_CLAIMS  # noqa: E402

SUITE = "testdata/cases/manifest.json"
GOLDEN = ROOT / "testdata" / "golden" / "baseline_results_v1.json"
APPROVALS = "testdata/approvals/candidate_v2_approvals.json"

# The intentional candidate regressions this demonstration must surface (see README and the
# candidate model manifest). If they disappear, the demo fails rather than looking "greener".
EXPECTED_DEMO_REGRESSIONS = ("rag-insufficient-001", "rag-supported-multi-001")


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "llm_eval_regression_lab.cli", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    enforce_offline()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifacts-dir", default=str(ROOT / "artifacts" / "demo"))
    parser.add_argument(
        "--candidate-fixture",
        default="candidate",
        choices=["baseline", "candidate"],
        help="for self-testing the demo only; the documented demo uses 'candidate'",
    )
    args = parser.parse_args(argv)
    out = Path(args.artifacts_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []

    print("== 1. Validate suite ==")
    result = cli("validate-suite", "--suite", SUITE)
    print(result.stdout.strip() or result.stderr.strip())
    if result.returncode != 0:
        problems.append("suite validation failed")

    print("\n== 2. Baseline runs (x2) ==")
    runs = []
    for index in (1, 2):
        path = out / f"baseline_run_{index}.json"
        result = cli("run", "--fixture", "baseline", "--suite", SUITE, "--output", str(path),
                     "--quiet")
        runs.append((result.returncode, path.read_bytes() if path.exists() else b""))
    golden = GOLDEN.read_bytes()
    baseline_ok = all(code == 0 for code, _ in runs)
    stable = runs[0][1] == runs[1][1] and runs[0][1] != b""
    matches_golden = runs[0][1] == golden
    print(f"run exit codes: {[code for code, _ in runs]}")
    print(f"byte-identical across runs: {stable}; byte-identical to golden: {matches_golden}")
    if baseline_ok and stable and matches_golden:
        summary = read_json(out / "baseline_run_1.json")["summary"]
        print(
            f"BASELINE: PASS ({summary['behavior_passed']}/{summary['behavior_cases']} behavior "
            f"cases passed, {summary['controls_detected']}/{summary['negative_controls']} "
            "negative controls detected, byte-identical to golden)"
        )
    else:
        print("BASELINE: FAIL")
        problems.append("baseline did not pass or is not byte-stable/golden-identical")

    print(f"\n== 3. Candidate run (fixture: {args.candidate_fixture}) ==")
    candidate_path = out / "candidate_run.json"
    result = cli("run", "--fixture", args.candidate_fixture, "--suite", SUITE, "--output",
                 str(candidate_path))
    print(result.stdout.strip() or result.stderr.strip())
    print(f"candidate run exit code: {result.returncode} (1 = candidate has failing cases)")

    print("\n== 4. Strict comparison: golden baseline vs candidate ==")
    comparison_path = out / "comparison.json"
    result = cli("compare", "--baseline", str(GOLDEN), "--candidate", str(candidate_path),
                 "--approvals", APPROVALS, "--strict", "--output", str(comparison_path))
    print(result.stdout.strip() or result.stderr.strip())
    regressions: tuple[str, ...] = ()
    if comparison_path.exists() and result.returncode in (0, 1):
        report = read_json(comparison_path)
        regressions = tuple(
            c["case_id"] for c in report["cases"] if c["classification"] == "regression"
        )
    manifest = load_model_manifest(fixture_manifest_path(ROOT, args.candidate_fixture))
    documented = tuple(sorted(n["case_id"] for n in manifest.documented_intentional_regressions))

    if (
        result.returncode == 1
        and regressions == EXPECTED_DEMO_REGRESSIONS
        and documented == EXPECTED_DEMO_REGRESSIONS
    ):
        print(
            "\nCANDIDATE STRICT COMPARISON: FAILED (expected demonstration) - intentional "
            f"regressions detected and blocking: {', '.join(regressions)}. This is a failing "
            "comparison, not a passing candidate."
        )
    else:
        print(
            "\nCANDIDATE STRICT COMPARISON: UNEXPECTED RESULT - "
            f"exit={result.returncode}, regressions={list(regressions)}, "
            f"documented={list(documented)}, expected={list(EXPECTED_DEMO_REGRESSIONS)}"
        )
        problems.append("candidate comparison did not surface exactly the documented regressions")

    print(f"\nArtifacts (safe to delete): {out}")
    print(f"NOTE: {NON_CLAIMS}")
    if problems:
        print("\nDEMO EXPECTATION FAILED: " + "; ".join(problems))
        return 1
    print("\nDEMO RESULT: OK - baseline passed; intentional candidate regression surfaced as "
          "designed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
