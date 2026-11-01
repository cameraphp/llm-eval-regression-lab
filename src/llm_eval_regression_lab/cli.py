"""Command-line interface. Offline and deterministic (NFR-001, NFR-002, REQ-016).

Exit codes: 0 = success, 1 = gate failure (failing run or blocking comparison),
2 = input, integrity, or comparability error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .canonical import read_json, sha256_json_file, sha256_text_file, write_canonical_json
from .manifests import fixture_manifest_path, load_model_manifest
from .offline import enforce_offline
from .regression import ComparisonError, compare_runs, load_approvals, run_suite
from .reporting import render_comparison, render_run_summary
from .schemas import SchemaError
from .suite import load_suite

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_INPUT_ERROR = 2


def _cmd_validate_suite(args: argparse.Namespace) -> int:
    suite = load_suite(Path(args.suite))
    print(
        f"SUITE OK: {suite.suite_id}@{suite.suite_version} - {len(suite.cases)} active cases, "
        f"corpus {suite.corpus.corpus_version} ({len(suite.corpus.documents)} documents), "
        f"manifest sha256 {suite.manifest_sha256}"
    )
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    suite = load_suite(Path(args.suite))
    manifest = load_model_manifest(fixture_manifest_path(Path(args.root), args.fixture))
    artifact = run_suite(suite, manifest, args.fixture)
    write_canonical_json(Path(args.output), artifact)
    if not args.quiet:
        print(render_run_summary(artifact), end="")
        print(f"Artifact written: {args.output}")
    return EXIT_OK if artifact["summary"]["run_passed"] else EXIT_GATE_FAILED


def _cmd_compare(args: argparse.Namespace) -> int:
    baseline = read_json(Path(args.baseline))
    candidate = read_json(Path(args.candidate))
    approvals, approvals_sha = (None, None)
    if args.approvals:
        approvals, approvals_sha = load_approvals(Path(args.approvals))
    report = compare_runs(
        baseline, candidate, approvals, strict=args.strict, approvals_sha256=approvals_sha
    )
    markdown = render_comparison(report)
    if args.output:
        output = Path(args.output)
        write_canonical_json(output, report)
        md_path = output.with_suffix(".md")
        md_path.write_bytes(markdown.encode("utf-8"))
    if not args.quiet:
        print(markdown, end="")
    return EXIT_GATE_FAILED if report["gate"]["result"] == "fail" else EXIT_OK


def _cmd_hash(args: argparse.Namespace) -> int:
    path = Path(args.path)
    digest = sha256_json_file(path) if path.suffix == ".json" else sha256_text_file(path)
    print(digest)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm_eval_regression_lab",
        description="Offline deterministic evaluation of rule-based test doubles against a "
        "synthetic benchmark. Synthetic benchmark evidence only.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate-suite", help="verify manifest, case hashes, change log, corpus")
    p.add_argument("--suite", required=True)
    p.set_defaults(func=_cmd_validate_suite)

    p = sub.add_parser("run", help="run a fixture over the suite and write a run artifact")
    p.add_argument("--fixture", required=True, choices=["baseline", "candidate"])
    p.add_argument("--suite", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--root", default=".", help="project root used to resolve model manifests")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("compare", help="compare a baseline and a candidate run artifact")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--approvals")
    p.add_argument(
        "--strict", action="store_true", help="also block on new_or_unapproved_behavior"
    )
    p.add_argument("--output", help="write comparison JSON here (and a .md alongside)")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=_cmd_compare)

    p = sub.add_parser("hash", help="print the canonical SHA-256 used in manifests")
    p.add_argument("--path", required=True)
    p.set_defaults(func=_cmd_hash)
    return parser


def main(argv: list[str] | None = None) -> int:
    enforce_offline()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SchemaError, ComparisonError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR


if __name__ == "__main__":
    sys.exit(main())
