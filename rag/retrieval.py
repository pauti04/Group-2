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

import hashlib
import os
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import faiss
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from rag.corpus import Document, load_documents
from rag.llm import LLMError, generate_resolution, grade_chunks
from specialist.tasks import TaskError

import threading

_index: _Index | None = None
_index_lock = threading.Lock()


def _load_or_build_index() -> _Index:
    global _index
    if _index is not None:
        return _index
    with _index_lock:
        if _index is not None:          # re-check: another thread may have built it while we waited
            return _index

        docs = load_documents()
        fingerprint = _corpus_fingerprint(docs)

        if CACHE_PATH.exists():
            try:
                with CACHE_PATH.open("rb") as f:
                    cached_fp, chunks, embeddings, bm25 = pickle.load(f)
                if cached_fp == fingerprint:
                    _index = _Index(chunks, embeddings, bm25)
                    return _index
            except Exception:
                pass

        chunks = _build_chunks(docs)
        embeddings = _embed([c.text for c in chunks])
        bm25 = BM25Okapi([_tokenize(c.text) for c in chunks])

        with CACHE_PATH.open("wb") as f:
            pickle.dump((fingerprint, chunks, embeddings, bm25), f)

        _index = _Index(chunks, embeddings, bm25)
        return _index



PROBLEM_SECTIONS = ("Description", "Symptoms", "When to Use")
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RRF_K = 60
CANDIDATES_FOR_GRADING = 8
CACHE_PATH = Path(__file__).resolve().parent / ".index_cache.pkl"


@dataclass
class Chunk:
    filename: str
    section: str
    text: str


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _build_chunks(docs: list[Document]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        for section in PROBLEM_SECTIONS:
            body = doc.sections.get(section)
            if body:
                chunks.append(Chunk(filename=doc.filename, section=section, text=body))
    return chunks


def _corpus_fingerprint(docs: list[Document]) -> str:
    h = hashlib.sha256()
    for doc in sorted(docs, key=lambda d: d.filename):
        h.update(doc.filename.encode())
        h.update(doc.text.encode())
    return h.hexdigest()


class _Index:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, bm25: BM25Okapi):
        self.chunks = chunks
        self.embeddings = embeddings
        self.bm25 = bm25
        self.faiss_index = faiss.IndexFlatIP(embeddings.shape[1])
        self.faiss_index.add(embeddings)


_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _embed(texts: list[str]) -> np.ndarray:
    vecs = _get_model().encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vecs.astype("float32")


def _load_or_build_index() -> _Index:
    docs = load_documents()
    fingerprint = _corpus_fingerprint(docs)

    if CACHE_PATH.exists():
        try:
            with CACHE_PATH.open("rb") as f:
                cached_fp, chunks, embeddings, bm25 = pickle.load(f)
            if cached_fp == fingerprint:
                return _Index(chunks, embeddings, bm25)
        except Exception:
            pass  # corrupt or stale cache — fall through and rebuild

    chunks = _build_chunks(docs)
    embeddings = _embed([c.text for c in chunks])
    bm25 = BM25Okapi([_tokenize(c.text) for c in chunks])

    with CACHE_PATH.open("wb") as f:
        pickle.dump((fingerprint, chunks, embeddings, bm25), f)

    return _Index(chunks, embeddings, bm25)


def _rrf_fuse(rank_lists: list[list[int]], k: int = RRF_K) -> list[int]:
    """Reciprocal Rank Fusion over lists of chunk indices, best-first."""
    scores: dict[int, float] = {}
    for ranking in rank_lists:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda i: scores[i], reverse=True)


def _dense_rank(index: _Index, question: str, top_n: int) -> list[int]:
    q_vec = _embed([question])
    _, idxs = index.faiss_index.search(q_vec, min(top_n, len(index.chunks)))
    return [int(i) for i in idxs[0] if i != -1]


def _sparse_rank(index: _Index, question: str, top_n: int) -> list[int]:
    scores = index.bm25.get_scores(_tokenize(question))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked[:top_n]


def answer_with_fusion_rag(question: str, needs: list | None = None) -> dict:
    """Return the Contract 2 payload. See rag/pipeline.py for the interface."""
    needs = needs or ["category", "resolution"]
    index = _load_or_build_index()

    pool_n = min(len(index.chunks), max(CANDIDATES_FOR_GRADING * 2, 10))
    dense_ranked = _dense_rank(index, question, pool_n)
    sparse_ranked = _sparse_rank(index, question, pool_n)
    fused = _rrf_fuse([dense_ranked, sparse_ranked])[:CANDIDATES_FOR_GRADING]
    candidates = [index.chunks[i] for i in fused]

    try:
        graded = grade_chunks(question, [c.text for c in candidates])
    except LLMError as exc:
        raise TaskError("LLM_ERROR", str(exc)) from exc

    surviving = [c for c, keep in zip(candidates, graded) if keep]
    if not surviving:
        raise TaskError(
            "NO_RELEVANT_CONTEXT",
            "No retrieved passage was graded as relevant to this question.",
        )

    # `surviving` is still in fused-rank order, so its first entry's document
    # is the answer. Dedup for `sources` while keeping that rank order.
    docs_by_name = {d.filename: d for d in load_documents()}
    winner = docs_by_name[surviving[0].filename]

    category = winner.ticket_category
    doc_resolution = winner.resolution
    if not category or not doc_resolution:
        raise TaskError(
            "NO_RELEVANT_CONTEXT",
            f"{winner.filename} is missing a Ticket Category or Resolution section.",
        )

    try:
        resolution = generate_resolution(question, doc_resolution)
    except LLMError as exc:
        raise TaskError("LLM_ERROR", str(exc)) from exc

    sources: list[str] = []
    for c in surviving:
        if c.filename not in sources:
            sources.append(c.filename)

    return {
        "category": category,
        "resolution": resolution,
        "sources": sources,
        "confidence": round(len(surviving) / len(candidates), 3),
    }
