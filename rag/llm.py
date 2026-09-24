"""Thin Groq wrapper for the RAG pipeline's two LLM calls: grading and generation.

Owner: person 2. Kept separate from retrieval.py so the fusion/ranking logic
stays readable and the two LLM calls are easy to reason about independently.
"""

from __future__ import annotations

import json
import os

from groq import Groq

MODEL = os.getenv("RAG_LLM_MODEL", "openai/gpt-oss-120b")


class LLMError(Exception):
    """Wraps any Groq call failure or unparseable response."""


_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set. Copy .env.example to .env and add a key.")
        _client = Groq(api_key=api_key)
    return _client


def grade_chunks(question: str, chunk_texts: list[str]) -> list[bool]:
    """Ask the LLM, for each chunk, whether it actually answers the question.

    One batched call rather than N calls per chunk, to keep latency and cost
    down; each chunk is numbered so the model's verdicts line up with input order.
    """
    if not chunk_texts:
        return []

    numbered = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(chunk_texts))
    prompt = (
        "You are grading whether each numbered passage below is directly "
        "relevant to answering the support question. Answer only with a JSON "
        'array of booleans, one per passage, e.g. [true, false, true]. No other text.\n\n'
        f"Question: {question}\n\nPassages:\n{numbered}"
    )

    raw = _complete(prompt)
    try:
        verdicts = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise LLMError(f"Grading response was not valid JSON: {raw!r}") from exc

    if not isinstance(verdicts, list) or len(verdicts) != len(chunk_texts):
        raise LLMError(f"Grading response had the wrong shape: {raw!r}")
    return [bool(v) for v in verdicts]


def generate_resolution(question: str, source_text: str) -> str:
    """Write 1-3 sentences of ticket resolution notes, grounded only in source_text."""
    prompt = (
        "Write 1 to 3 sentences of support-ticket resolution notes for the "
        "issue below, using only the information in the source text. Do not "
        "add steps that are not present in the source text. Return plain "
        "text only, no JSON, no markdown, no preamble.\n\n"
        f"Issue: {question}\n\nSource text:\n{source_text}"
    )
    text = _complete(prompt).strip()
    if not text:
        raise LLMError("Generation returned an empty response.")
    return text


def _complete(prompt: str) -> str:
    try:
        response = _get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - any SDK/network failure is an LLM_ERROR
        raise LLMError(f"Groq call failed: {exc}") from exc
    return response.choices[0].message.content or ""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()