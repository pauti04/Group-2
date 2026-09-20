"""Day-one stub retriever — deterministic, no API key, no model downloads.

Owner: nobody. This exists so that persons 1, 3 and 4 can run the whole system
end to end on the first day while person 2 builds the real pipeline. It scores
documents by keyword overlap against the Symptoms/Description sections, then
reads the answer straight out of the winning document's own `## Resolution` and
`## Ticket Category` sections.

It is genuinely grounded in the knowledge base (so the integration is real), but
it does no embedding, no chunking and no LLM call — which is exactly what
person 2 replaces in rag/retrieval.py and rag/pipeline.py.

DELETE THIS FILE once the real pipeline lands.
"""

from __future__ import annotations

import re

from rag.corpus import Document, load_documents

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "is", "are", "was", "were", "be",
    "been", "to", "of", "in", "on", "for", "with", "my", "i", "it", "that", "this",
    "cannot", "can", "not", "do", "does", "did", "have", "has", "had", "at", "as",
    "from", "by", "me", "they", "their", "there", "when", "what", "user", "users",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _score(question_tokens: set[str], doc: Document) -> float:
    """Overlap against the parts of a doc that describe *problems*, not fixes."""
    haystack = " ".join(
        doc.sections.get(name, "") for name in ("Description", "Symptoms", "When to Use")
    ) or doc.text
    doc_tokens = _tokens(haystack)
    if not question_tokens or not doc_tokens:
        return 0.0
    return len(question_tokens & doc_tokens) / len(question_tokens)


def retrieve(question: str, top_k: int = 2) -> list[tuple[Document, float]]:
    question_tokens = _tokens(question)
    scored = [(doc, _score(question_tokens, doc)) for doc in load_documents()]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
