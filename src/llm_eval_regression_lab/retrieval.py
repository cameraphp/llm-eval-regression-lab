"""Deterministic token-overlap retrieval over the synthetic corpus (REQ-006).

This is intentionally simple lexical retrieval: it is transparent and reproducible, and makes no
claim about retrieval quality on real data.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from .corpus import Corpus

_TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
        "how", "i", "in", "is", "it", "must", "of", "on", "or", "should", "the", "this", "to",
        "what", "when", "which", "who", "with",
    }
)  # fmt: skip


@dataclass(frozen=True)
class RetrievedDocument:
    document_id: str
    score: int


def tokenize(text: str) -> list[str]:
    """NFKC, lowercase, ``[a-z0-9]+`` tokens, stop words removed. Order preserved."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return [token for token in _TOKEN.findall(normalized) if token not in STOPWORDS]


def retrieve(
    question: str, corpus: Corpus, scope: Iterable[str], top_k: int
) -> list[RetrievedDocument]:
    """Score in-scope documents by distinct shared tokens; drop zero scores; stable order.

    Ordering: score descending, then ``document_id`` ascending. Documents outside ``scope`` or
    absent from the corpus are never considered.
    """
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    query_tokens = set(tokenize(question))
    scored: list[RetrievedDocument] = []
    for document_id in sorted(set(scope)):
        document = corpus.get(document_id)
        if document is None:
            continue
        doc_tokens = set(tokenize(document.title + " " + document.content))
        score = len(query_tokens & doc_tokens)
        if score > 0:
            scored.append(RetrievedDocument(document_id=document_id, score=score))
    scored.sort(key=lambda item: (-item.score, item.document_id))
    return scored[:top_k]
