"""Protocol tests for the A2A layer (step 3).

Covers every requirement the assignment lists for step 3: unique task ids, an
immediate acknowledgment, the four statuses, status checking, result retrieval
— plus the failure paths the Requester has to survive.
"""

from __future__ import annotations

import time

import pytest
import requests

from requester.a2a_client import A2AError, SpecialistClient

QUESTION = "I forgot my password and cannot log into my account."


# -- acknowledgment and task ids ------------------------------------------

def test_submit_acknowledges_immediately_with_a_task_id(specialist):
    base_url, store = specialist
    store.work_delay_s = 2.0  # work will still be pending when we get the ack

    started = time.monotonic()
    response = requests.post(f"{base_url}/tasks", json={"question": QUESTION})
    elapsed = time.monotonic() - started

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"]
    assert body["status"] == "submitted"
    # The ack must not wait for the work — that is the whole point of the
    # submit/poll split.
    assert elapsed < 1.0, f"ack took {elapsed:.2f}s, should be immediate"


def test_task_ids_are_unique(specialist):
    base_url, _ = specialist
    ids = {requests.post(f"{base_url}/tasks", json={"question": QUESTION}).json()["task_id"]
           for _ in range(5)}
    assert len(ids) == 5


# -- the lifecycle ---------------------------------------------------------

def test_task_reaches_completed_and_carries_a_result(specialist):
    base_url, _ = specialist
    client = SpecialistClient(base_url=base_url, timeout_s=10)

    task = client.ask(QUESTION, needs=["category", "resolution"])

    assert task.result["category"] == "Account Access"
    assert task.result["resolution"]
    assert task.result["sources"]
    assert task.polls >= 1


def test_history_records_every_state_change(specialist):
    base_url, _ = specialist
    client = SpecialistClient(base_url=base_url, timeout_s=10)

    task = client.ask(QUESTION)
    states = [change["state"] for change in task.history]

    assert states[0] == "submitted"
    assert states[-1] == "completed"
    assert "working" in states
    assert all(change["at"] for change in task.history)


def test_status_is_observable_while_working(specialist):
    base_url, store = specialist
    store.work_delay_s = 1.0
    client = SpecialistClient(base_url=base_url, timeout_s=10)

    seen = []
    client.on_status = lambda task_id, status, polls: seen.append(status)
    client.ask(QUESTION)

    assert "submitted" in seen
    assert seen[-1] == "completed"


# -- failure paths ---------------------------------------------------------

def test_unretrievable_question_fails_the_task(specialist):
    base_url, _ = specialist
    client = SpecialistClient(base_url=base_url, timeout_s=10)

    with pytest.raises(A2AError) as excinfo:
        client.ask("What is the capital of France?")

    assert excinfo.value.code == "NO_RELEVANT_CONTEXT"


def test_failed_task_carries_an_error_and_no_result(specialist):
    base_url, _ = specialist
    task_id = requests.post(f"{base_url}/tasks",
                            json={"question": "What is the capital of France?"}).json()["task_id"]

    for _ in range(40):
        body = requests.get(f"{base_url}/tasks/{task_id}").json()
        if body["status"] in {"completed", "failed", "canceled"}:
            break
        time.sleep(0.05)

    assert body["status"] == "failed"
    assert body["error"]["code"] == "NO_RELEVANT_CONTEXT"
    assert "result" not in body


def test_unknown_task_is_a_404(specialist):
    base_url, _ = specialist
    response = requests.get(f"{base_url}/tasks/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_TASK"


def test_submit_without_a_question_is_rejected(specialist):
    base_url, _ = specialist
    response = requests.post(f"{base_url}/tasks", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_timeout_gives_up_and_cancels_the_task(specialist):
    base_url, store = specialist
    store.work_delay_s = 30.0  # far longer than the client will wait
    client = SpecialistClient(base_url=base_url, timeout_s=1.0)

    task_id = client.submit(QUESTION)
    with pytest.raises(A2AError) as excinfo:
        client.poll_until_done(task_id)

    assert excinfo.value.code == "TIMEOUT"
    # The Requester should not leave work running that it will never read.
    for _ in range(20):
        status = requests.get(f"{base_url}/tasks/{task_id}").json()["status"]
        if status == "canceled":
            break
        time.sleep(0.05)
    assert status == "canceled"


def test_unreachable_specialist_is_reported_not_hung(specialist):
    _, _ = specialist
    client = SpecialistClient(base_url="http://127.0.0.1:1", timeout_s=5, max_retries=2)

    with pytest.raises(A2AError) as excinfo:
        client.ask(QUESTION)

    assert excinfo.value.code == "SPECIALIST_UNREACHABLE"


# -- cancellation ----------------------------------------------------------

def test_cancel_stops_a_submitted_task(specialist):
    base_url, store = specialist
    store.work_delay_s = 5.0

    task_id = requests.post(f"{base_url}/tasks", json={"question": QUESTION}).json()["task_id"]
    body = requests.post(f"{base_url}/tasks/{task_id}/cancel").json()

    assert body["status"] == "canceled"
    assert requests.get(f"{base_url}/tasks/{task_id}").json()["status"] == "canceled"


def test_cancelling_a_finished_task_is_harmless(specialist):
    base_url, _ = specialist
    client = SpecialistClient(base_url=base_url, timeout_s=10)
    task_id = client.submit(QUESTION)
    client.poll_until_done(task_id)

    response = requests.post(f"{base_url}/tasks/{task_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


# -- discovery -------------------------------------------------------------

def test_agent_card_describes_the_specialist(specialist):
    base_url, _ = specialist
    card = SpecialistClient(base_url=base_url).agent_card()

    assert card["name"]
    assert card["skills"][0]["id"] == "classify_and_resolve"
    assert set(card["task_states"]) == {"submitted", "working", "completed",
                                        "failed", "canceled"}
