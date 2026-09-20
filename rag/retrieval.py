"""Advanced RAG — fusion retrieval + relevance grading.

Owner: person 2. THIS FILE IS THE ASSIGNMENT'S "advanced technique" (2 points).

=============================================================================
Why fusion retrieval for this corpus
=============================================================================
The seven knowledge-base documents share a lot of boilerplate: "Restart the
computer if appropriate" appears in four of them, and every file has the same
Description/Symptoms/Troubleshooting/Resolution skeleton. Pure dense retrieval
blurs documents that are lexically distinct but semantically similar, which is
exactly the failure mode that matters here — confusing `network.md` with
`hardware.md` puts the wrong value in the dropdown.

Fusion retrieval (BM25 + dense embeddings, combined with Reciprocal Rank
Fusion) keeps the keyword signal that distinguishes "Wi-Fi" from "keyboard"
while retaining the semantic signal that connects "cannot log in" to
"account locked". It sits outside the foundational 1-6 techniques.

The second half — grading retrieved chunks for relevance before generating —
is what produces our NO_RELEVANT_CONTEXT failure path honestly, instead of
letting the LLM answer from its own knowledge when the KB has nothing.

Measure it: run harness/run_all.py with RAG_BACKEND=stub and again with
RAG_BACKEND=real, and put the comparison in the report.

=============================================================================
TODO (person 2)
=============================================================================
1. Chunk the documents (rag.corpus.load_documents gives you parsed sections;
   section-aware chunking is likely better here than fixed-size windows).
2. Build the dense index: sentence-transformers embeddings -> FAISS.
3. Build the sparse index: rank_bm25 over the same chunks.
4. Fuse the two ranked lists with RRF: score = sum(1 / (k + rank)), k ~= 60.
5. Grade the top chunks with the LLM: "does this chunk answer the question?"
   Drop chunks that fail. If nothing survives, raise TaskError.
6. Generate the final JSON with the LLM, given only the surviving chunks.
7. Cache the index to disk so the server does not rebuild it on every boot.
"""

from __future__ import annotations

from specialist.tasks import TaskError


def answer_with_fusion_rag(question: str, needs: list | None = None) -> dict:
    """Return the Contract 2 payload. See rag/pipeline.py for the interface.

    Must raise TaskError("NO_RELEVANT_CONTEXT", ...) when grading rejects
    every retrieved chunk, and TaskError("LLM_ERROR", ...) if the model call
    fails or returns output that will not parse.
    """
    raise TaskError(
        "LLM_ERROR",
        "Real RAG pipeline not implemented yet. Run with RAG_BACKEND=stub.",
    )
