# Requirements: `llm-eval-regression-lab`

- **Spec date:** 2026-10-31
- **ID scheme:** `REQ-nnn` functional, `NFR-nnn` non-functional, `SAFE-nnn` safety and honesty.
  IDs are stable: a retired ID is marked *withdrawn* and never reused.
- **Proof:** every ID maps to named tests in [`validation.md`](validation.md).

## Functional requirements

### REQ-001 Synthetic, versioned corpus
The corpus file has a `corpus_version`, and so does every document. Each document has `document_id`,
`corpus_version`, `title`, `content`, `synthetic: true` and `allowed_for_benchmark: true`. The loader
rejects any of the following:
- a document that is missing a field;
- a document that is non-synthetic or not allowed for benchmarking;
- a duplicate `document_id`;
- a per-document version that differs from the corpus version.

The corpus hash is the SHA-256 of its canonical JSON.

### REQ-002 Versioned case manifest
`testdata/cases/manifest.json` declares `suite_id`, `suite_version`, a corpus reference (path, version,
SHA-256), and one entry per case version (`case_id`, `case_version`, `path`, `sha256`, `status`). The
loader rejects all of the following:
- a case file whose canonical SHA-256 differs from the manifest;
- a case file whose id or version differs from its entry;
- a duplicate `(case_id, case_version)`;
- more than one active version of a case;
- an entry without a matching `change_log` record;
- a missing superseded file;
- a corpus reference that does not match.

Changing an expected behavior requires a version bump and a change-log entry. Historical files are
kept.

### REQ-003 Case contract
Every case has:
- `case_id`, `case_version`, `suite_version` and `category`;
- `mode` (`behavior` or `negative_control`);
- `synthetic_fixture_note` and `input.question`;
- `retrieval_scope`, a list of corpus document IDs, which may be empty;
- `expected`: `decision`, `reason_code`, `required_answer_fragments`, `forbidden_answer_fragments`,
  `required_citations`, `claims` (each with `claim_id`, `fragment` and `support_document_ids`), and
  `min_groundedness`.

An `answer` expectation needs at least one claim and one required citation. A non-answer
expectation needs a documented reason code and no claims or citations. Unknown fields are rejected.

### REQ-004 Structured response schema
A response must be a JSON object with exactly these fields:
`case_id`, `decision`, `answer`, `citations`, `reason_code`, `message`, `prompt_id`, `prompt_version`,
`model_id` and `model_version`.

The schema rejects:
- unparseable JSON;
- missing or extra fields;
- wrong types;
- an unknown `decision`;
- a citation that is not exactly `{document_id, supporting_quote}` with non-empty strings;
- versions that are not semantic versions.

The failure code is `SCHEMA_INVALID`. (`reason_code` replaces the single `refusal_reason` field
from the original sketch, so that both non-answer pathways get controlled codes.)

### REQ-005 Decision-specific invariants
- `answer`: a non-empty `answer`, at least one citation, and null `reason_code` and `message`.
- `insufficient_evidence`: null `answer`, no citations, `reason_code` in
  {`NO_RETRIEVED_CONTEXT`, `EVIDENCE_NOT_FOUND`}, and `message` equal to that code's controlled text.
- `refusal`: null `answer`, no citations, `reason_code` in {`POLICY_RESTRICTED_CREDENTIAL_REQUEST`},
  and `message` equal to that code's controlled text.

If a non-answer response carries an answer or citations, the code is `UNSUPPORTED_ANSWER_LEAKAGE`.
Any other invariant breach is `DECISION_INVARIANT_VIOLATION`.

### REQ-006 Deterministic retrieval
Tokenization applies NFKC, lowercases, extracts `[a-z0-9]+` and drops a fixed stop-word list.
Retrieval only considers documents in the case's `retrieval_scope`. The score is the number of
distinct shared tokens. Documents scoring zero are excluded. Ties are broken by ascending
`document_id`, and `top_k` comes from the model manifest. An empty scope yields empty context.

### REQ-007 Citation validation
For each citation, checked in this order, the first failure applies:
1. The document exists in the corpus. Otherwise: `CITATION_UNKNOWN_DOCUMENT`.
2. The document is in the case scope. Otherwise: `CITATION_OUT_OF_SCOPE`.
3. The normalized `supporting_quote` is a substring of the normalized document content. Otherwise:
   `CITATION_QUOTE_NOT_FOUND`.

Normalization is NFKC, lowercase and whitespace collapse. Each required citation document must
appear among the *valid* citations, otherwise the code is `CITATION_REQUIRED_MISSING`.

### REQ-008 Answer fragment checks
In an observed answer, every required fragment must be present, otherwise the code is
`ANSWER_FRAGMENT_MISSING`. No forbidden fragment may appear, otherwise the code is
`ANSWER_FORBIDDEN_FRAGMENT`. Matching is a normalized substring match.

### REQ-009 Fixture-bound groundedness and claim coverage
A claim is supported when both of these hold:
- its fragment appears in the answer;
- its fragment appears in the `supporting_quote` of a valid citation whose document is listed in
  the claim's `support_document_ids`.

Groundedness is supported claims divided by total claims, rounded to 4 decimals. The run artifact
also records the integer counts. Each unsupported claim yields `CLAIM_UNSUPPORTED`. Groundedness
below `min_groundedness` yields `GROUNDEDNESS_BELOW_MIN`.

The answer is split into sentences. Every sentence must contain at least one supported claim
fragment, otherwise the code is `ANSWER_SENTENCE_UNSUPPORTED`. This is how unsupported extra claims
are caught. All of this is lexical and fixture-bound, not semantic entailment.

### REQ-010 Insufficient-evidence pathway
If retrieval returns no documents, the simulator returns `insufficient_evidence` with
`NO_RETRIEVED_CONTEXT`. If documents are retrieved but no rule's evidence is available, it returns
`insufficient_evidence` with `EVIDENCE_NOT_FOUND`.

The evaluator flags any substantive answer given where a non-answer was expected:
`DECISION_MISMATCH` and `UNSUPPORTED_ANSWER_LEAKAGE`, plus the answer checks. A wrong reason code
yields `REASON_CODE_MISMATCH`.

### REQ-011 Refusal pathway
Refusal rules are checked before retrieval. A matching request returns `refusal` with the rule's
documented reason code and controlled message. It never contains an answer, citations or restricted
detail. Refusal and insufficient evidence are distinct decisions with distinct reason codes.

### REQ-012 Prompt and model version tracking
Prompt files carry front matter with `prompt_id` and a semantic `prompt_version`. The prompt hash is
the SHA-256 of the file's UTF-8 bytes with LF line endings. Each model manifest declares `model_id`,
semantic `model_version`, `kind: rule_based_test_double`, `is_ai_inference: false` and a prompt
reference (path, id, version, sha256). The loader rejects a prompt whose hash, id or version differs
from the pin.

`behavior_revision` is the SHA-256 of the canonical behavior block. Response metadata must equal the
active manifest's prompt and model id and version, otherwise the code is `METADATA_MISMATCH`. A
wrong `case_id` is `CASE_ID_MISMATCH`.

### REQ-013 Canonical run artifact
A run artifact records:
- `artifact_schema_version`, `synthetic_benchmark_only: true` and `fixture_mode`;
- the fixture name and `evaluator_version`;
- the suite id, version and manifest hash;
- the corpus version, hash and document count;
- the prompt id, version and hash;
- the model id, version, kind, behavior revision and manifest hash;
- per-case results: id, version, hash, mode, category, status, expected and observed decision,
  retrieved IDs, checks, failure codes, groundedness and counts, response hash, behavior
  fingerprint and observed response;
- aggregate counts and the non-claims text.

It is serialized as canonical JSON.

### REQ-014 Negative-control cases
A negative-control case supplies an injected response, either as an object or as raw text. In an
injected object, `"<<ACTIVE>>"` in a metadata field means "use the active manifest's value". The
case also lists `expected_failure_codes`. The control counts as detected only when the evaluator's
failure-code set **exactly equals** the expected set. A missed or over-reported control makes the
run fail.

The suite includes these controls: an out-of-scope citation, a valid ID with an invented quote, an
unsupported extra claim, malformed JSON, and a prompt/model version mismatch.

### REQ-015 Baseline vs candidate comparison
The comparator takes two run artifacts and an optional approvals file. It classifies every case in
the union of case IDs (sorted) as `pass`, `regression`, `expected_failure_demo` or
`new_or_unapproved_behavior`, using the rules in plan.md §4.5. It refuses to compare (exit 2) when:
- either artifact is not `synthetic_benchmark_only`;
- the schema versions differ;
- the suite ids differ;
- the corpus hashes differ;
- the evaluator versions differ.

### REQ-016 Gate, approvals and exit codes
The `compare` command exits `1` when there is any `regression`, and in `--strict` mode also when
there is any `new_or_unapproved_behavior`. Otherwise it exits `0`. Input or comparability errors
exit `2`.

An approval covers a case only when its `case_id`, `case_version`, baseline fingerprint and
candidate fingerprint all match exactly. Approvals never apply to a `regression`. The `run` command
exits `0` when every behavior case passes and every control is detected, and `1` otherwise. The
artifact is still written either way.

### REQ-017 Golden baseline
`testdata/golden/baseline_results_v1.json` is the reviewed baseline artifact. A fresh baseline run
must be byte-identical to it. Rebaselining is an explicit, documented step whose diff must be
reviewed.

### REQ-018 Demo script
`scripts/run_demo.py` does the following:
1. Validates the suite.
2. Runs the baseline twice and checks that both runs are byte-identical to each other and to the
   golden file.
3. Runs the candidate.
4. Runs the strict comparison, which must exit `1` with exactly the documented intentional
   regressions.

It prints the baseline as PASS and the candidate as an expected demonstration of a **failed**
comparison. It exits `0` only if every expectation holds. If anything deviates, it prints
`DEMO EXPECTATION FAILED` and exits `1`.

### REQ-019 Simulators are declared test doubles
The baseline and candidate behaviors are declarative rules in their model manifests: refusal rules,
answer rules with trigger terms and fixed answers and citations, and retrieval settings. Simulator
output is never described as AI or model inference.

The candidate differs from the baseline only by:
- documented intentional variants: an approved wording change, a citation-attribution regression,
  and an answer-leakage regression;
- its version metadata.

## Non-functional requirements

### NFR-001 Determinism
For identical inputs, repeated runs, including separate processes with different `PYTHONHASHSEED`
values, produce byte-identical artifacts. Artifacts contain no timestamps, randomness, or absolute or
machine-specific paths.

### NFR-002 Offline execution
Tests, CLI and demo need no network. The CLI installs a socket guard before doing any work, and the
test session runs under the same guard. Source modules import no network client libraries.

### NFR-003 Minimal, pinned toolchain
The core uses only the standard library: `[project].dependencies` is empty. The dev tools are
exactly `pytest` and `ruff`, pinned with `==` in `pyproject.toml` and recorded in
`requirements-dev.lock`.

### NFR-004 Lint cleanliness
`python -m ruff check .` reports no findings.

### NFR-005 Portability of evidence
Files are written as UTF-8 with `\n` line endings. Text is hashed LF-normalized, and artifact paths
are relative POSIX paths.

### NFR-006 Spec-to-test traceability
Every requirement ID in this file appears in the traceability matrix of `validation.md`. Every test
that `validation.md` references exists in `tests/`.

## Safety and honesty requirements

### SAFE-001 No network, model SDK or vector store
There is no dependency on, or import of, any LLM or model SDK, LangChain, embedding or vector-store
client, or HTTP client. Only `offline.py` imports `socket`, to block it.

### SAFE-002 No secrets
There is no `.env` file. No project file contains credential-like patterns (API key prefixes, private
key blocks, cloud access key IDs). `.gitignore` excludes `.env*` except examples.

### SAFE-003 No Git operations
Source code does not import `subprocess` and does not call `git`. Neither the scripts nor the tests
call `git`. The build process creates no `.git` directory, and this is recorded in BUILD_REPORT.md.

### SAFE-004 Synthetic data only
The corpus and every case are synthetic and labelled so. Every case has a `synthetic_fixture_note`.
No real person, organization, customer, medical or financial data is used.

### SAFE-005 Benchmark evidence vs production non-claims
Every run artifact and comparison report carries `synthetic_benchmark_only: true` and the
non-claims text. The CLI summaries print it, and README.md has a prominent section stating it.

### SAFE-006 Intentional regression is never hidden
The comparator ignores the candidate's documentation-only `documented_intentional_regressions`
field, so documented regressions are still classified `regression` and block the gate. The demo
fails if the baseline fails, or if the documented regression no longer appears.

## Requirement-to-validation summary

| ID | Primary test module(s) |
|---|---|
| REQ-001 | `tests/test_schemas.py` |
| REQ-002 | `tests/test_regression.py` |
| REQ-003 | `tests/test_schemas.py` |
| REQ-004 | `tests/test_schemas.py`, `tests/test_evaluators.py` |
| REQ-005 | `tests/test_schemas.py` |
| REQ-006 | `tests/test_retrieval.py` |
| REQ-007 | `tests/test_evaluators.py` |
| REQ-008 | `tests/test_evaluators.py` |
| REQ-009 | `tests/test_evaluators.py` |
| REQ-010 | `tests/test_evaluators.py` |
| REQ-011 | `tests/test_evaluators.py` |
| REQ-012 | `tests/test_regression.py`, `tests/test_evaluators.py` |
| REQ-013 | `tests/test_regression.py` |
| REQ-014 | `tests/test_evaluators.py` |
| REQ-015 | `tests/test_regression.py` |
| REQ-016 | `tests/test_regression.py`, `tests/test_offline_demo.py` |
| REQ-017 | `tests/test_regression.py`, `tests/test_offline_demo.py` |
| REQ-018 | `tests/test_offline_demo.py` |
| REQ-019 | `tests/test_regression.py` |
| NFR-001 | `tests/test_offline_demo.py`, `tests/test_retrieval.py` |
| NFR-002 | `tests/test_offline_demo.py`, `tests/test_traceability.py` |
| NFR-003 | `tests/test_traceability.py` |
| NFR-004 | `python -m ruff check .` |
| NFR-005 | `tests/test_offline_demo.py` |
| NFR-006 | `tests/test_traceability.py` |
| SAFE-001 | `tests/test_traceability.py` |
| SAFE-002 | `tests/test_traceability.py` |
| SAFE-003 | `tests/test_traceability.py` |
| SAFE-004 | `tests/test_schemas.py`, `tests/test_traceability.py` |
| SAFE-005 | `tests/test_regression.py`, `tests/test_traceability.py` |
| SAFE-006 | `tests/test_regression.py`, `tests/test_offline_demo.py` |

The full mapping (implementation, test names, commands, expected results, artifacts, failure
interpretation) is in `validation.md`.
