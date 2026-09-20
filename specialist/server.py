"""Specialist Agent — HTTP surface for the A2A protocol.

Owner: person 1.

Run it:
    python -m specialist.server                 # normal
    python -m specialist.server --delay 3       # visible `working` state
    python -m specialist.server --delay 999     # force the Requester to time out

This module knows nothing about RAG beyond calling `rag.pipeline.answer`, and
nothing at all about the web form. See CONTRACTS.md.
"""

from __future__ import annotations

import argparse

from flask import Flask, jsonify, request

from rag.pipeline import answer
from specialist.tasks import TaskStore

app = Flask(__name__)
store = TaskStore()


@app.post("/tasks")
def submit_task():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": {"code": "BAD_REQUEST",
                                  "message": "Field 'question' is required."}}), 400

    needs = payload.get("needs") or ["category", "resolution"]
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
        return jsonify({"error": {"code": "UNKNOWN_TASK",
                                  "message": f"No task with id {task_id}."}}), 404
    return jsonify(task.to_dict()), 200


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


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
