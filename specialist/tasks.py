"""In-memory task store and lifecycle for the Specialist Agent.

Owner: person 1.

A task moves submitted -> working -> (completed | failed). The work itself runs
on a background thread so that POST /tasks can acknowledge immediately, which is
what makes the Requester's polling loop meaningful rather than decorative.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


SUBMITTED = "submitted"
WORKING = "working"
COMPLETED = "completed"
FAILED = "failed"

TERMINAL = {COMPLETED, FAILED}


class TaskError(Exception):
    """Raised by a worker to fail a task with a specific A2A error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Task:
    task_id: str
    question: str
    status: str = SUBMITTED
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize exactly as CONTRACTS.md describes: never both result and error."""
        payload: dict[str, Any] = {"task_id": self.task_id, "status": self.status}
        if self.status == COMPLETED and self.result is not None:
            payload["result"] = self.result
        if self.status == FAILED and self.error is not None:
            payload["error"] = self.error
        return payload


class TaskStore:
    """Thread-safe task registry. One instance per running server."""

    def __init__(self, work_delay_s: float = 0.0) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        # Artificial delay before the worker starts. Keeps the `working` state
        # observable in the demo video, and gives us a knob for the timeout
        # scenario without having to break the RAG pipeline.
        self.work_delay_s = work_delay_s

    def submit(self, question: str, worker: Callable[[str], dict[str, Any]]) -> Task:
        task = Task(task_id=str(uuid.uuid4()), question=question)
        with self._lock:
            self._tasks[task.task_id] = task
        threading.Thread(target=self._run, args=(task, worker), daemon=True).start()
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def _run(self, task: Task, worker: Callable[[str], dict[str, Any]]) -> None:
        if self.work_delay_s:
            time.sleep(self.work_delay_s)
        with self._lock:
            task.status = WORKING
        try:
            result = worker(task.question)
        except TaskError as exc:
            self._fail(task, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - any worker crash becomes a failed task
            self._fail(task, "LLM_ERROR", f"{type(exc).__name__}: {exc}")
        else:
            with self._lock:
                task.result = result
                task.status = COMPLETED

    def _fail(self, task: Task, code: str, message: str) -> None:
        with self._lock:
            task.error = {"code": code, "message": message}
            task.status = FAILED
