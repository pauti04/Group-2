"""Specialist Agent — HTTP surface for the A2A protocol.

Owner: person 1.

Run it:
    python -m specialist.server                 # normal
    python -m specialist.server --delay 3       # visible `working` state
    python -m specialist.server --delay 999     # force the Requester to time out

Endpoints:
    GET  /.well-known/agent-card.json   what this agent is and can do
    POST /tasks                         submit, acknowledged immediately
    GET  /tasks/<id>                    status, and the result once it exists
    POST /tasks/<id>/cancel             stop a task we no longer need
    GET  /health                        liveness

This module knows nothing about RAG beyond calling `rag.pipeline.answer`, and
nothing at all about the web form. See CONTRACTS.md.
"""

from __future__ import annotations

import argparse

from flask import Flask, jsonify, request

from rag.pipeline import answer
from specialist.agent_card import AGENT_CARD
from specialist.tasks import PROTOCOL_VERSION, TERMINAL, TaskStore

app = Flask(__name__)
store = TaskStore()


def _error(code: str, message: str, http_status: int):
    return jsonify({"error": {"code": code, "message": message},
                    "protocol_version": PROTOCOL_VERSION}), http_status


@app.get("/.well-known/agent-card.json")
def agent_card():
    return jsonify(AGENT_CARD), 200


@app.get("/.well-known/agent.json")
def agent_card_legacy():
    """Alias — earlier drafts of the A2A spec used this path."""
    return jsonify(AGENT_CARD), 200


@app.post("/tasks")
def submit_task():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return _error("BAD_REQUEST", "Field 'question' is required.", 400)

    needs = payload.get("needs") or ["category", "resolution"]
    if not isinstance(needs, list) or not all(isinstance(n, str) for n in needs):
        return _error("BAD_REQUEST", "Field 'needs' must be a list of strings.", 400)

    # The worker closes over `needs` so specialist.tasks stays a generic task
    # runner that knows nothing about RAG.
    task = store.submit(question, worker=lambda q: answer(q, needs=needs))
    app.logger.info("task %s submitted: %r", task.task_id, question)
    # Acknowledge immediately — the work is already running on another thread.
    return jsonify(task.to_dict()), 201


@app.get("/tasks/<task_id>")
def get_task(task_id: str):
    task = store.get(task_id)
    if task is None:
        return _error("UNKNOWN_TASK", f"No task with id {task_id}.", 404)
    return jsonify(task.to_dict()), 200


@app.post("/tasks/<task_id>/cancel")
def cancel_task(task_id: str):
    task = store.cancel(task_id)
    if task is None:
        return _error("UNKNOWN_TASK", f"No task with id {task_id}.", 404)
    if task.status in TERMINAL and not task.cancel_requested:
        # Already finished before the cancel arrived. Not an error — the caller
        # gets the terminal state and can read the result if there is one.
        return jsonify(task.to_dict()), 200
    return jsonify(task.to_dict()), 200


@app.get("/health")
def health():
    return jsonify({"status": "ok", "protocol_version": PROTOCOL_VERSION}), 200


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Specialist Agent.")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--delay", type=float, default=0.0,
                        help="Seconds to stall before working. Use a large value "
                             "to demonstrate the Requester's timeout handling.")
    args = parser.parse_args()

    store.work_delay_s = args.delay
    app.run(port=args.port, threaded=True)


if __name__ == "__main__":
    main()
