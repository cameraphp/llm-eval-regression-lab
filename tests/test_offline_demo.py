"""CLI and demo through real subprocesses: determinism, offline mode, exit codes, demo honesty.

REQ-016, REQ-017, REQ-018, NFR-001, NFR-002, NFR-005, SAFE-006.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import APPROVALS_PATH, GOLDEN_PATH, PROJECT_ROOT

from llm_eval_regression_lab.offline import OfflineViolationError, is_offline_enforced

SUITE = "testdata/cases/manifest.json"


def run(args: list[str], *, seed: str | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    if seed is not None:
        env["PYTHONHASHSEED"] = seed
    return subprocess.run(
        [sys.executable, *args], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        check=False, timeout=120,
    )


def cli(*args: str, seed: str | None = None) -> subprocess.CompletedProcess[str]:
    return run(["-m", "llm_eval_regression_lab.cli", *args], seed=seed)


def test_cli_baseline_run_is_byte_stable_across_processes(tmp_path):
    outputs = []
    for seed in ("1", "4242"):
        out = tmp_path / f"baseline_{seed}.json"
        result = cli("run", "--fixture", "baseline", "--suite", SUITE, "--output", str(out),
                     "--quiet", seed=seed)
        assert result.returncode == 0, result.stderr
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    assert outputs[0] == GOLDEN_PATH.read_bytes()


def test_cli_strict_compare_fails_for_candidate(tmp_path):
    candidate = tmp_path / "candidate_run.json"
    run_result = cli("run", "--fixture", "candidate", "--suite", SUITE, "--output", str(candidate),
                     "--quiet")
    assert run_result.returncode == 1  # candidate has failing behavior cases
    report_path = tmp_path / "comparison.json"
    result = cli("compare", "--baseline", str(GOLDEN_PATH), "--candidate", str(candidate),
                 "--approvals", str(APPROVALS_PATH), "--strict", "--output", str(report_path))
    assert result.returncode == 1
    assert "GATE: FAIL" in result.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert sorted(report["gate"]["blocking_cases"]) == [
        "rag-insufficient-001",
        "rag-supported-multi-001",
    ]
    assert report_path.with_suffix(".md").is_file()


def test_cli_compare_baseline_against_golden_passes(tmp_path):
    baseline = tmp_path / "baseline_run.json"
    assert cli("run", "--fixture", "baseline", "--suite", SUITE, "--output", str(baseline),
               "--quiet").returncode == 0
    result = cli("compare", "--baseline", str(GOLDEN_PATH), "--candidate", str(baseline),
                 "--strict")
    assert result.returncode == 0, result.stdout
    assert "GATE: PASS" in result.stdout


def test_cli_run_exit_codes(tmp_path):
    assert cli("validate-suite", "--suite", SUITE).returncode == 0
    missing = cli("run", "--fixture", "baseline", "--suite", "does/not/exist.json", "--output",
                  str(tmp_path / "x.json"))
    assert missing.returncode == 2
    assert "ERROR" in missing.stderr

    shutil.copytree(PROJECT_ROOT / "testdata", tmp_path / "testdata")
    case_file = tmp_path / "testdata" / "cases" / "v1" / "policy_refusal.json"
    obj = json.loads(case_file.read_text(encoding="utf-8"))
    obj["expected"]["forbidden_answer_fragments"] = []
    case_file.write_text(json.dumps(obj), encoding="utf-8")
    tampered = cli("validate-suite", "--suite", str(tmp_path / "testdata/cases/manifest.json"))
    assert tampered.returncode == 2
    assert "sha256 mismatch" in tampered.stderr


def test_demo_script_reports_baseline_pass_and_expected_regression(tmp_path):
    result = run(["scripts/run_demo.py", "--artifacts-dir", str(tmp_path / "demo")])
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "BASELINE: PASS (5/5 behavior cases passed, 5/5 negative controls detected" in out
    assert "CANDIDATE STRICT COMPARISON: FAILED (expected demonstration)" in out
    assert "rag-insufficient-001, rag-supported-multi-001" in out
    assert "DEMO RESULT: OK" in out
    assert "BASELINE: FAIL" not in out
    assert "DEMO EXPECTATION FAILED" not in out
    assert (tmp_path / "demo" / "comparison.json").is_file()


def test_demo_fails_if_regression_disappears(tmp_path):
    # Using the baseline as the "candidate" removes the regression: the demo must refuse to
    # report success instead of presenting a greener result.
    result = run(["scripts/run_demo.py", "--artifacts-dir", str(tmp_path / "demo"),
                  "--candidate-fixture", "baseline"])
    assert result.returncode == 1
    assert "DEMO EXPECTATION FAILED" in result.stdout
    assert "FAILED (expected demonstration)" not in result.stdout


def test_offline_guard_blocks_network():
    assert is_offline_enforced()
    with pytest.raises(OfflineViolationError):
        socket.create_connection(("127.0.0.1", 9), timeout=1)
    with pytest.raises(OfflineViolationError):
        socket.getaddrinfo("example.invalid", 80)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OfflineViolationError):
            sock.connect(("127.0.0.1", 9))
    finally:
        sock.close()
    # The CLI entry point installs the same guard in a fresh process.
    code = (
        "import socket\n"
        "from llm_eval_regression_lab import cli\n"
        "cli.main(['hash', '--path', 'pyproject.toml'])\n"
        "socket.create_connection(('127.0.0.1', 9), timeout=1)\n"
    )
    result = run(["-c", code])
    assert result.returncode != 0
    assert "OfflineViolationError" in result.stderr


def test_no_timestamps_or_absolute_paths_in_golden():
    text = GOLDEN_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)
    assert not re.search(r"[A-Za-z]:[\\/]", text)
    assert str(PROJECT_ROOT) not in text
    assert str(Path.home()) not in text
    for key in ("timestamp", "created_at", "generated_at", "hostname", "random"):
        assert f'"{key}"' not in text


def test_artifacts_use_lf_and_relative_paths():
    data = GOLDEN_PATH.read_bytes()
    assert b"\r\n" not in data
    assert data.endswith(b"}\n")
    golden = json.loads(data.decode("utf-8"))
    for case in golden["cases"]:
        path = case["case_path"]
        assert "\\" not in path and not path.startswith("/") and ":" not in path
