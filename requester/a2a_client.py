"""A2A client — the Requester's half of the protocol.

Owner: person 1. Speaks only the protocol in CONTRACTS.md; knows nothing about
RAG or the browser.

Three things here beyond a plain HTTP call, each for a reason:

* **Retries.** A dropped connection is not the same as a failed task. We retry
  transient transport errors and 5xx a few times with backoff before giving up,
  so a blip does not fail a ticket that would otherwise have succeeded.
* **Polling backoff.** Fixed-interval polling either spams a fast task or
  crawls on a slow one. We start tight and widen, which keeps the demo snappy
  without hammering the Specialist on a long RAG call.
* **Cancel on timeout.** When we stop waiting, we tell the Specialist so. Left
  out, a timed-out task keeps running and burns an LLM call nobody will read.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:5005"

#: Non-terminal states — keep polling.
ACTIVE_STATES = {"submitted", "working"}


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
    history: list = field(default_factory=list)


class SpecialistClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout_s: float = 30.0,
                 poll_interval_s: float = 0.25, max_poll_interval_s: float = 2.0,
                 max_retries: int = 3, on_status=None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.max_poll_interval_s = max_poll_interval_s
        self.max_retries = max_retries
        # Callback so the harness can log every status transition — that log is
        # what makes the demo video legible.
        self.on_status = on_status or (lambda task_id, status, polls: None)

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs):
        """One HTTP call, retried on transport errors and 5xx.

        A 4xx is never retried: the Specialist understood us and said no.
        """
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = requests.request(method, url, timeout=10, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code < 500:
                    return response
                last_error = A2AError("SPECIALIST_ERROR",
                                      f"{response.status_code}: {response.text[:200]}")

            if attempt < self.max_retries - 1:
                time.sleep(0.25 * (2 ** attempt))  # 0.25s, 0.5s

        raise A2AError(
            "SPECIALIST_UNREACHABLE",
            f"{method} {url} failed after {self.max_retries} attempts: {last_error}",
        )

    # -- protocol ----------------------------------------------------------

    def agent_card(self) -> dict:
        """Fetch the Specialist's card. Discovery, not required for the flow."""
        return self._request("GET", "/.well-known/agent-card.json").json()

    def submit(self, question: str, needs: list | None = None) -> str:
        payload = {"question": question}
        if needs:
            payload["needs"] = needs

        response = self._request("POST", "/tasks", json=payload)
        if response.status_code != 201:
            error = (response.json() or {}).get("error", {})
            raise A2AError(error.get("code", "BAD_REQUEST"),
                           error.get("message", f"Submit failed ({response.status_code})."))

        body = response.json()
        self.on_status(body["task_id"], body["status"], 0)
        return body["task_id"]

    def cancel(self, task_id: str) -> None:
        """Best effort. Used when we have stopped waiting — never raises."""
        try:
            self._request("POST", f"/tasks/{task_id}/cancel")
        except A2AError:
            pass

    def poll_until_done(self, task_id: str) -> TaskResult:
        started = time.monotonic()
        interval = self.poll_interval_s
        polls = 0

        while True:
            if time.monotonic() - started > self.timeout_s:
                # Stop the work we are no longer going to read.
                self.cancel(task_id)
                raise A2AError(
                    "TIMEOUT",
                    f"Task {task_id} did not finish within {self.timeout_s:.0f}s "
                    f"(polled {polls} times). Cancellation was requested.",
                )

            response = self._request("GET", f"/tasks/{task_id}")
            polls += 1

            if response.status_code == 404:
                raise A2AError("UNKNOWN_TASK", f"Specialist does not recognise task {task_id}.")

            body = response.json()
            status = body["status"]
            self.on_status(task_id, status, polls)

            if status == "completed":
                return TaskResult(task_id=task_id, result=body["result"], polls=polls,
                                  elapsed_ms=int((time.monotonic() - started) * 1000),
                                  history=body.get("history", []))
            if status == "failed":
                error = body.get("error", {})
                raise A2AError(error.get("code", "LLM_ERROR"),
                               error.get("message", "The Specialist reported a failure."))
            if status == "canceled":
                raise A2AError("CANCELED", f"Task {task_id} was canceled.")

            if status not in ACTIVE_STATES:
                # An unknown state means the Specialist is speaking a protocol
                # version we do not understand. Stop rather than poll forever.
                raise A2AError("PROTOCOL_ERROR",
                               f"Specialist returned unknown status {status!r}.")

            time.sleep(interval)
            interval = min(interval * 1.5, self.max_poll_interval_s)

    def ask(self, question: str, needs: list | None = None) -> TaskResult:
        """Submit and poll. The whole A2A round trip in one call."""
        return self.poll_until_done(self.submit(question, needs))
