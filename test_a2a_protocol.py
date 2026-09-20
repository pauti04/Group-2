"""Regression tests for the Step 3 asynchronous A2A lifecycle."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from requester.a2a_client import A2AError, SpecialistClient
from specialist import server
from specialist.tasks import TaskError, TaskStore


RESULT = {
    "category": "Network",
    "resolution": "Check the network connection.",
    "sources": ["network.md"],
    "confidence": 0.9,
}


class _Response:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> dict:
        return self._body


class SpecialistApiLifecycleTests(unittest.TestCase):
    """Exercise the actual Flask endpoints without starting a TCP server."""

    def setUp(self) -> None:
        self.original_store = server.store
        # The delay is deliberately *while working*, which lets this test prove
        # that the state can be retrieved over the HTTP interface.
        server.store = TaskStore(work_delay_s=0.1)
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def tearDown(self) -> None:
        server.store = self.original_store

    def _wait_for(self, task_id: str, status: str) -> dict:
        deadline = time.monotonic() + 1.0
        last = None
        while time.monotonic() < deadline:
            response = self.client.get(f"/tasks/{task_id}")
            self.assertEqual(response.status_code, 200)
            last = response.get_json()
            if last["status"] == status:
                return last
            time.sleep(0.01)
        self.fail(f"Task {task_id} never reached {status!r}; last response: {last}")

    @patch("specialist.server.answer", return_value=RESULT)
    def test_submission_acknowledges_then_exposes_working_and_completed(self, _answer) -> None:
        acknowledgment = self.client.post("/tasks", json={"question": "Wi-Fi is down"})

        self.assertEqual(acknowledgment.status_code, 201)
        ack_body = acknowledgment.get_json()
        self.assertEqual(ack_body["status"], "submitted")
        self.assertRegex(ack_body["task_id"], r"^[0-9a-f-]{36}$")

        working = self._wait_for(ack_body["task_id"], "working")
        self.assertNotIn("result", working)
        self.assertNotIn("error", working)

        completed = self._wait_for(ack_body["task_id"], "completed")
        self.assertEqual(completed["result"], RESULT)
        self.assertNotIn("error", completed)

    @patch("specialist.server.answer", return_value=RESULT)
    def test_each_submission_receives_a_unique_uuid_task_id(self, _answer) -> None:
        first = self.client.post("/tasks", json={"question": "first request"}).get_json()
        second = self.client.post("/tasks", json={"question": "second request"}).get_json()

        self.assertEqual(first["status"], "submitted")
        self.assertEqual(second["status"], "submitted")
        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertRegex(first["task_id"], r"^[0-9a-f-]{36}$")
        self.assertRegex(second["task_id"], r"^[0-9a-f-]{36}$")

    @patch(
        "specialist.server.answer",
        side_effect=TaskError("NO_RELEVANT_CONTEXT", "No matching knowledge-base content."),
    )
    def test_worker_failure_is_retrievable_as_a_terminal_failed_task(self, _answer) -> None:
        acknowledgment = self.client.post("/tasks", json={"question": "unrelated question"})

        failed = self._wait_for(acknowledgment.get_json()["task_id"], "failed")
        self.assertEqual(failed["error"], {
            "code": "NO_RELEVANT_CONTEXT",
            "message": "No matching knowledge-base content.",
        })
        self.assertNotIn("result", failed)

    def test_unknown_task_returns_contract_error(self) -> None:
        response = self.client.get("/tasks/not-a-known-task")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "UNKNOWN_TASK")


class RequesterPollingTests(unittest.TestCase):
    def test_client_polls_nonterminal_states_and_returns_completed_result(self) -> None:
        statuses = []
        client = SpecialistClient(poll_interval_s=0, on_status=lambda *event: statuses.append(event))

        with patch(
            "requester.a2a_client.requests.post",
            return_value=_Response(201, {"task_id": "task-1", "status": "submitted"}),
        ), patch(
            "requester.a2a_client.requests.get",
            side_effect=[
                _Response(200, {"task_id": "task-1", "status": "submitted"}),
                _Response(200, {"task_id": "task-1", "status": "working"}),
                _Response(200, {"task_id": "task-1", "status": "completed", "result": RESULT}),
            ],
        ):
            result = client.ask("Wi-Fi is down")

        self.assertEqual(result.task_id, "task-1")
        self.assertEqual(result.result, RESULT)
        self.assertEqual(result.polls, 3)
        self.assertEqual(
            statuses,
            [
                ("task-1", "submitted", 0),
                ("task-1", "submitted", 1),
                ("task-1", "working", 2),
                ("task-1", "completed", 3),
            ],
        )

    def test_client_stops_polling_and_raises_specialist_failure(self) -> None:
        client = SpecialistClient(poll_interval_s=0)

        with patch(
            "requester.a2a_client.requests.post",
            return_value=_Response(201, {"task_id": "task-2", "status": "submitted"}),
        ), patch(
            "requester.a2a_client.requests.get",
            return_value=_Response(200, {
                "task_id": "task-2",
                "status": "failed",
                "error": {"code": "LLM_ERROR", "message": "The worker crashed."},
            }),
        ):
            with self.assertRaisesRegex(A2AError, "The worker crashed") as caught:
                client.ask("Wi-Fi is down")

        self.assertEqual(caught.exception.code, "LLM_ERROR")

    def test_client_times_out_while_a_task_stays_nonterminal(self) -> None:
        client = SpecialistClient(timeout_s=0.5, poll_interval_s=0)

        with patch(
            "requester.a2a_client.requests.get",
            return_value=_Response(200, {"task_id": "task-3", "status": "working"}),
        ) as get, patch(
            "requester.a2a_client.time.monotonic",
            side_effect=[0.0, 0.0, 1.0],
        ):
            with self.assertRaisesRegex(A2AError, "within 0.5s") as caught:
                client.poll_until_done("task-3")

        self.assertEqual(caught.exception.code, "TIMEOUT")
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
