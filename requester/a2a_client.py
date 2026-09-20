"""A2A client — submit, poll, time out.

Owner: person 3. Speaks only the protocol in CONTRACTS.md; knows nothing about
RAG or the browser.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:5005"


class A2AError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class TaskResult:
    task_id: str
    result: dict
    polls: int
    elapsed_ms: int


class SpecialistClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout_s: float = 30.0,
                 poll_interval_s: float = 0.5, on_status=None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        # Callback so the harness can log every status transition — that log is
        # what makes the demo video legible.
        self.on_status = on_status or (lambda task_id, status, polls: None)

    def submit(self, question: str, needs: list | None = None) -> str:
        payload = {"question": question}
        if needs:
            payload["needs"] = needs
        try:
            response = requests.post(f"{self.base_url}/tasks", json=payload, timeout=10)
        except requests.RequestException as exc:
            raise A2AError("SPECIALIST_UNREACHABLE",
                           f"Could not reach the Specialist at {self.base_url}: {exc}") from exc
        if response.status_code != 201:
            raise A2AError("BAD_REQUEST", f"Submit failed ({response.status_code}): {response.text}")

        body = response.json()
        self.on_status(body["task_id"], body["status"], 0)
        return body["task_id"]

    def poll_until_done(self, task_id: str) -> TaskResult:
        started = time.monotonic()
        polls = 0
        while True:
            if time.monotonic() - started > self.timeout_s:
                raise A2AError(
                    "TIMEOUT",
                    f"Task {task_id} did not finish within {self.timeout_s:.0f}s "
                    f"(polled {polls} times).",
                )
            try:
                response = requests.get(f"{self.base_url}/tasks/{task_id}", timeout=10)
            except requests.RequestException as exc:
                raise A2AError("SPECIALIST_UNREACHABLE",
                               f"Lost contact with the Specialist: {exc}") from exc

            polls += 1
            if response.status_code == 404:
                raise A2AError("UNKNOWN_TASK", f"Specialist does not recognise task {task_id}.")

            body = response.json()
            status = body["status"]
            self.on_status(task_id, status, polls)

            if status == "completed":
                return TaskResult(task_id=task_id, result=body["result"], polls=polls,
                                  elapsed_ms=int((time.monotonic() - started) * 1000))
            if status == "failed":
                error = body.get("error", {})
                raise A2AError(error.get("code", "LLM_ERROR"),
                               error.get("message", "The Specialist reported a failure."))

            time.sleep(self.poll_interval_s)

    def ask(self, question: str, needs: list | None = None) -> TaskResult:
        """Submit and poll. The whole A2A round trip in one call."""
        return self.poll_until_done(self.submit(question, needs))
