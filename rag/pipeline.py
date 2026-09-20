"""RAG pipeline — the single seam between person 2's work and everyone else's.

Owner: person 2.

The only thing the rest of the system knows about RAG is this function:

    answer(question) -> {"category", "resolution", "sources", "confidence"}

It raises TaskError("NO_RELEVANT_CONTEXT", ...) when retrieval finds nothing
useful, which the Specialist turns into a `failed` task and the Requester
reports without touching the browser. Keep that behaviour when you swap the
stub out — it is one of our three documented failure scenarios.

Set RAG_BACKEND=real in .env once rag/retrieval.py is ready.
"""

from __future__ import annotations

import os

from specialist.tasks import TaskError

# Below this, we declare the knowledge base has nothing useful to say rather
# than letting the LLM improvise an answer. Tune with evidence and write the
# number down in the report.
RELEVANCE_THRESHOLD = float(os.getenv("RAG_RELEVANCE_THRESHOLD", "0.15"))


def answer(question: str, needs: list | None = None) -> dict:
    """Answer a Requester question from the knowledge base.

    `needs` is what the Requester asked for, e.g. ["category", "resolution"].
    The stub always returns both. The real pipeline should use it to shape the
    LLM prompt — that framing belongs here, not on the wire, because sending it
    as part of the question pollutes the retrieval query.
    """
    needs = needs or ["category", "resolution"]
    backend = os.getenv("RAG_BACKEND", "stub").lower()
    if backend == "real":
        from rag.retrieval import answer_with_fusion_rag

        return answer_with_fusion_rag(question, needs=needs)
    return _answer_with_stub(question)


def _answer_with_stub(question: str) -> dict:
    from rag import stub

    ranked = stub.retrieve(question, top_k=2)
    if not ranked or ranked[0][1] < RELEVANCE_THRESHOLD:
        raise TaskError(
            "NO_RELEVANT_CONTEXT",
            f"No knowledge base document scored above {RELEVANCE_THRESHOLD} for this question.",
        )

    best, score = ranked[0]
    category = best.ticket_category
    resolution = best.resolution
    if not category or not resolution:
        raise TaskError(
            "NO_RELEVANT_CONTEXT",
            f"{best.filename} is missing a Ticket Category or Resolution section.",
        )

    # Keep the resolution to the first couple of sentences so it reads like
    # ticket notes rather than a pasted document.
    resolution = " ".join(resolution.split("\n\n")[:2]).strip()

    return {
        "category": category,
        "resolution": resolution,
        "sources": [doc.filename for doc, s in ranked if s > 0],
        "confidence": round(score, 3),
    }
