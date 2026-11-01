"""Spec traceability and static safety policies.

NFR-003, NFR-004, NFR-006, SAFE-001, SAFE-002, SAFE-003, SAFE-004, SAFE-005.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib

from conftest import PROJECT_ROOT

from llm_eval_regression_lab.canonical import read_json
from llm_eval_regression_lab.reporting import NON_CLAIMS

SPEC_DIR = PROJECT_ROOT / "specs" / "2026-10-31-llm-eval-regression"
ID_PATTERN = re.compile(r"\b(?:REQ|NFR|SAFE)-\d{3}\b")
SRC = PROJECT_ROOT / "src" / "llm_eval_regression_lab"

FORBIDDEN_IMPORTS = {
    # network clients
    "aiohttp", "ftplib", "http", "httpx", "requests", "smtplib", "ssl", "urllib", "urllib3",
    "websocket", "websockets", "xmlrpc",
    # model SDKs / orchestration / vector stores / embeddings
    "anthropic", "openai", "google", "vertexai", "boto3", "botocore", "azure", "cohere",
    "mistralai", "huggingface_hub", "transformers", "sentence_transformers", "langchain",
    "langchain_core", "llama_index", "chromadb", "pinecone", "weaviate", "qdrant_client",
    "faiss", "tiktoken",
}  # fmt: skip


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _test_functions():
    names = set()
    for path in (PROJECT_ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names.update(
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
    return names


def _matrix_rows(text):
    section = text.split("## 3. Traceability matrix", 1)[1]
    return {
        m.group(0): line
        for line in section.splitlines()
        if line.startswith("| ") and (m := ID_PATTERN.search(line.split("|")[1]))
    }


# ---- NFR-006 traceability ---------------------------------------------------------------------


def test_specs_exist_with_required_sections():
    plan = (SPEC_DIR / "plan.md").read_text(encoding="utf-8")
    requirements = (SPEC_DIR / "requirements.md").read_text(encoding="utf-8")
    validation = (SPEC_DIR / "validation.md").read_text(encoding="utf-8")
    for heading in ("## 2. Scope", "## 3. Architecture", "## 5. Reproducibility",
                    "## 6. Fixture versioning", "## 7. Risk controls"):
        assert heading in plan, heading
    assert "## Requirement-to-validation summary" in requirements
    assert "## 3. Traceability matrix" in validation


def test_every_requirement_has_validation_entry():
    requirements = (SPEC_DIR / "requirements.md").read_text(encoding="utf-8")
    validation = (SPEC_DIR / "validation.md").read_text(encoding="utf-8")
    defined = set(re.findall(r"^### ((?:REQ|NFR|SAFE)-\d{3})\b", requirements, re.M))
    assert len(defined) >= 30
    rows = _matrix_rows(validation)
    sections = set(re.findall(r"^### ((?:REQ|NFR|SAFE)-\d{3})\b", validation, re.M))
    assert defined == set(rows), sorted(defined ^ set(rows))
    assert defined == sections, sorted(defined ^ sections)
    for req_id, row in rows.items():
        tests_cell = row.split("|")[3]
        assert "test_" in tests_cell, f"{req_id} has no named test"


def test_validation_references_existing_tests():
    validation = (SPEC_DIR / "validation.md").read_text(encoding="utf-8")
    referenced = set(re.findall(r"\b(test_[a-z0-9_]+)\b(?!\.py)", validation))
    existing = _test_functions()
    missing = sorted(referenced - existing)
    assert not missing, f"validation.md references unknown tests: {missing}"
    # And every test module named in validation.md exists.
    for module in set(re.findall(r"(test_[a-z_]+\.py)", validation)):
        assert (PROJECT_ROOT / "tests" / module).is_file(), module


# ---- NFR-003 / NFR-004 toolchain --------------------------------------------------------------


def test_runtime_dependencies_are_empty_and_dev_pinned():
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == []
    dev = project["project"]["optional-dependencies"]["dev"]
    assert sorted(d.split("==")[0] for d in dev) == ["pytest", "ruff"]
    assert all(re.fullmatch(r"[a-z]+==\d+\.\d+\.\d+", d) for d in dev)
    lock = (PROJECT_ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
    for pin in dev:
        assert pin in lock


def test_ruff_check_passes():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=False, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---- SAFE-001 no network / model SDK ----------------------------------------------------------


def test_source_has_no_network_or_model_sdk_imports():
    for path in sorted(SRC.glob("*.py")):
        names = _imports(path)
        assert not names & FORBIDDEN_IMPORTS, (path.name, names & FORBIDDEN_IMPORTS)
        if path.name != "offline.py":
            assert "socket" not in names, path.name


# ---- SAFE-002 no secrets ----------------------------------------------------------------------

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
]
SKIP_DIRS = {".venv", ".pytest_cache", ".ruff_cache", "artifacts", "__pycache__"}


def _project_files():
    for path in PROJECT_ROOT.rglob("*"):
        rel = path.relative_to(PROJECT_ROOT)
        if path.is_file() and not (set(rel.parts) & SKIP_DIRS) and ".egg-info" not in str(rel):
            yield rel, path


def test_no_secret_files_or_credential_patterns():
    for rel, path in _project_files():
        assert not (rel.name.startswith(".env") and rel.name != ".env.example"), rel
        assert rel.suffix not in {".pem", ".key", ".p12", ".pfx"}, rel
        if rel.name == "test_traceability.py":
            continue  # contains the patterns themselves
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text), (rel, pattern.pattern)


def test_gitignore_excludes_env_and_artifacts():
    lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for required in (".env", ".env.*", "artifacts/", ".venv/"):
        assert required in lines, required


# ---- SAFE-003 no Git operations ---------------------------------------------------------------


def test_source_does_not_invoke_subprocess_or_git():
    for path in sorted(SRC.glob("*.py")):
        names = _imports(path)
        assert "subprocess" not in names, path.name
        assert "os" not in names, path.name  # no os.system / exec paths in the core
    git_call = re.compile(r"""["']git["']|\bgit\s+(init|commit|push|remote|add)\b""")
    for folder in ("src", "scripts", "tests"):
        for path in (PROJECT_ROOT / folder).rglob("*.py"):
            if path.name == "test_traceability.py":
                continue
            assert not git_call.search(path.read_text(encoding="utf-8")), path


# ---- SAFE-004 synthetic data only -------------------------------------------------------------


def test_fixtures_are_labelled_synthetic():
    corpus = read_json(PROJECT_ROOT / "testdata" / "corpus" / "synthetic_corpus_v1.json")
    assert corpus["synthetic"] is True
    assert all(doc["title"].startswith("Synthetic") for doc in corpus["documents"])
    assert read_json(PROJECT_ROOT / "testdata" / "cases" / "manifest.json")["synthetic"] is True
    assert read_json(
        PROJECT_ROOT / "testdata" / "approvals" / "candidate_v2_approvals.json"
    )["synthetic"] is True
    for path in (PROJECT_ROOT / "testdata" / "cases" / "v1").glob("*.json"):
        assert "synthetic" in read_json(path)["synthetic_fixture_note"].lower(), path.name


# ---- SAFE-005 non-claims ----------------------------------------------------------------------


def test_readme_contains_non_claims_statement():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Benchmark evidence vs production non-claims" in readme
    required = (
        "This project evaluates deterministic fixtures against a small synthetic benchmark. "
        "Results demonstrate that the included checks execute as designed for these fixtures "
        "only. They do not establish real LLM, RAG, safety, groundedness, or production "
        "performance."
    )
    plain = " ".join(readme.replace(">", " ").replace("*", "").split())  # drop quote/bold marks
    assert required in plain
    assert NON_CLAIMS.startswith(required)
