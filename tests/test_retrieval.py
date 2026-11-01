"""Deterministic token-overlap retrieval (REQ-006, NFR-001)."""

from __future__ import annotations

from llm_eval_regression_lab.corpus import validate_corpus_dict
from llm_eval_regression_lab.retrieval import retrieve, tokenize

ALL = ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")


def ids(results):
    return [r.document_id for r in results]


def test_tokenize_is_lowercase_and_drops_stopwords():
    assert tokenize("What is the Per-Diem allowance for TRAVEL?") == [
        "per",
        "diem",
        "allowance",
        "travel",
    ]
    # NFKC folds compatibility characters (fullwidth digits/letters) before tokenizing.
    assert tokenize("１４ Days") == ["14", "days"]
    assert tokenize("the and of to") == []


def test_retrieval_respects_scope(corpus):
    question = "When is the fictional head office open?"
    assert ids(retrieve(question, corpus, ALL, top_k=5))[0] == "SYN-005"
    in_scope = retrieve(question, corpus, ["SYN-001", "SYN-002"], top_k=5)
    assert "SYN-005" not in ids(in_scope)
    # Unknown IDs in a scope are ignored, never fabricated.
    assert ids(retrieve(question, corpus, ["SYN-999"], top_k=5)) == []


def test_retrieval_orders_by_score_then_document_id():
    corpus = validate_corpus_dict(
        {
            "corpus_version": "t",
            "description": "synthetic test corpus",
            "synthetic": True,
            "documents": [
                {
                    "document_id": doc_id,
                    "corpus_version": "t",
                    "title": "Doc",
                    "content": content,
                    "synthetic": True,
                    "allowed_for_benchmark": True,
                }
                for doc_id, content in [
                    ("D-3", "alpha beta"),
                    ("D-1", "alpha beta"),
                    ("D-2", "alpha beta gamma"),
                    ("D-4", "alpha"),
                ]
            ],
        }
    )
    results = retrieve("alpha beta gamma", corpus, ["D-4", "D-3", "D-2", "D-1"], top_k=10)
    assert [(r.document_id, r.score) for r in results] == [
        ("D-2", 3),
        ("D-1", 2),
        ("D-3", 2),
        ("D-4", 1),
    ]


def test_retrieval_excludes_zero_overlap_and_empty_scope(corpus):
    assert retrieve("zebra quantum xylophone", corpus, ALL, top_k=5) == []
    assert retrieve("When is the fictional head office open?", corpus, [], top_k=5) == []


def test_retrieval_applies_top_k(corpus):
    question = "synthetic policy requests"
    full = retrieve(question, corpus, ALL, top_k=5)
    assert len(full) > 2
    assert ids(retrieve(question, corpus, ALL, top_k=2)) == ids(full)[:2]


def test_retrieval_is_repeatable(corpus):
    question = "How many days before departure must a travel request be submitted?"
    first = retrieve(question, corpus, ALL, top_k=3)
    for scope in (ALL, tuple(reversed(ALL)), ALL + ALL):
        assert retrieve(question, corpus, scope, top_k=3) == first
