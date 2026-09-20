"""Task lifecycle for the Specialist Agent — the server half of the A2A layer.

Owner: person 1. See CONTRACTS.md for the wire format.

A task moves submitted -> working -> (completed | failed | canceled). The work
runs on a background thread so POST /tasks can acknowledge immediately, which is
what makes the Requester's polling loop meaningful rather than decorative.

Every state change is timestamped and kept in the task's history, so a finished
task can still show what it did and when — the Requester sees only the current
state while polling, but the history is what we show in the report and the demo.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

PROTOCOL_VERSION = "1.0"

SUBMITTED = "submitted"
WORKING = "working"
COMPLETED = "completed"
FAILED = "failed"
CANCELED = "canceled"

#: Non-terminal states. The Requester keeps polling while a task is in one.
ACTIVE = {SUBMITTED, WORKING}
#: Terminal states. The Requester stops polling.
TERMINAL = {COMPLETED, FAILED, CANCELED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TaskError(Exception):
    """Raised by a worker to fail a task with a specific A2A error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class StateChange:
    state: str
    at: str

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state, "at": self.at}


@dataclass
class Task:
    task_id: str
    question: str
    status: str = SUBMITTED
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    history: list[StateChange] = field(default_factory=list)
    cancel_requested: bool = False
    created_at: str = field(default_factory=_now)

    def to_dict(self, include_history: bool = True) -> dict[str, Any]:
        """Serialize for the wire. Never carries both result and error."""
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status,
            "protocol_version": PROTOCOL_VERSION,
            "created_at": self.created_at,
        }
        if self.status == COMPLETED and self.result is not None:
            payload["result"] = self.result
        if self.status == FAILED and self.error is not None:
            payload["error"] = self.error
        if self.cancel_requested and self.status in ACTIVE:
            # Cancellation is cooperative: the worker cannot be killed mid-call,
            # so a task can be still `working` with a cancel pending. Say so
            # rather than letting the Requester think the cancel was ignored.
            payload["cancel_requested"] = True
        if include_history:
            payload["history"] = [change.to_dict() for change in self.history]
        return payload


class TaskStore:
    """Thread-safe task registry. One instance per running server."""

    def __init__(self, work_delay_s: float = 0.0) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        # Artificial delay before a worker starts. Keeps the `working` state
        # observable in the demo, and gives us a knob for the timeout scenario
        # without having to break the RAG pipeline to produce one.
        self.work_delay_s = work_delay_s

    # -- lifecycle ---------------------------------------------------------

    def submit(self, question: str, worker: Callable[[str], dict[str, Any]]) -> Task:
        task = Task(task_id=str(uuid.uuid4()), question=question)
        task.history.append(StateChange(SUBMITTED, task.created_at))
        with self._lock:
            self._tasks[task.task_id] = task
        threading.Thread(target=self._run, args=(task, worker), daemon=True).start()
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> Task | None:
        """Request cancellation. Returns the task, or None if it is unknown.

        A task still in `submitted` is canceled immediately. One already
        `working` cannot be interrupted — a Python thread in the middle of an
        embedding lookup or an LLM call will not stop on request — so we set a
        flag and the worker discards its result when it finishes. Already
        terminal tasks are left alone.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status in TERMINAL:
                return task
            task.cancel_requested = True
            if task.status == SUBMITTED:
                self._transition(task, CANCELED)
            return task

    # -- internals ---------------------------------------------------------

    def _transition(self, task: Task, state: str) -> None:
        """Move a task to a new state. Caller must hold the lock."""
        task.status = state
        task.history.append(StateChange(state, _now()))

    def _run(self, task: Task, worker: Callable[[str], dict[str, Any]]) -> None:
        if not self._sleep_unless_canceled(task, self.work_delay_s):
            return

        with self._lock:
            if task.cancel_requested:
                self._transition(task, CANCELED)
                return
            self._transition(task, WORKING)

        try:
            result = worker(task.question)
        except TaskError as exc:
            self._finish_error(task, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - any worker crash becomes a failed task
            self._finish_error(task, "LLM_ERROR", f"{type(exc).__name__}: {exc}")
        else:
            with self._lock:
                if task.cancel_requested:
                    # Cancel landed while the worker was running. Throw the
                    # result away rather than completing a task the Requester
                    # has already stopped waiting for.
                    self._transition(task, CANCELED)
                    return
                task.result = result
                self._transition(task, COMPLETED)

    def _sleep_unless_canceled(self, task: Task, seconds: float) -> bool:
        """Sleep in slices so a cancel does not have to wait out the delay.

        Returns False if the task was canceled while sleeping.
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with self._lock:
                if task.cancel_requested:
                    if task.status not in TERMINAL:
                        self._transition(task, CANCELED)
                    return False
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return True

    def _finish_error(self, task: Task, code: str, message: str) -> None:
        with self._lock:
            if task.cancel_requested:
                self._transition(task, CANCELED)
                return
            task.error = {"code": code, "message": message}
            self._transition(task, FAILED)
