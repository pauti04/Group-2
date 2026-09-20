"""Command line entry point for the Requester Agent.

    python -m requester.cli "I forgot my password and cannot log into my account."
    python -m requester.cli --all          # every case in test_cases.json

Prints each A2A status transition, so you can see the submitted -> working ->
completed lifecycle rather than take it on faith.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from requester.a2a_client import SpecialistClient
from requester.coordinator import Outcome, handle_request
from requester.form_plan import DryRunSubmitter

TEST_CASES = Path(__file__).resolve().parent.parent / "test_cases.json"


def _log_status(task_id: str, status: str, polls: int) -> None:
    where = "ack" if polls == 0 else f"poll {polls}"
    print(f"    [a2a] {where:<8} task={task_id[:8]}  status={status}")


def run_one(text: str, client: SpecialistClient, expected: str | None = None) -> Outcome:
    print(f"\n>>> {text}")
    submitter = DryRunSubmitter()
    outcome = handle_request(text, client=client, submitter=submitter)

    if outcome.ok:
        plan = submitter.last_plan
        print(f"    [rag] category={outcome.category!r} "
              f"confidence={outcome.confidence} sources={outcome.sources}")
        print(f"    [form] #issue      = {plan.issue}")
        print(f"    [form] #category   = {plan.category_option}")
        print(f"    [form] #resolution = {plan.resolution}")
    print(f"    {outcome.summary()}")

    if expected and outcome.category and outcome.category != expected:
        print(f"    !!! category mismatch: expected {expected!r}, got {outcome.category!r}")
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Requester Agent.")
    parser.add_argument("request", nargs="?", help="The user's support request.")
    parser.add_argument("--all", action="store_true", help="Run every test case.")
    parser.add_argument("--url", default="http://127.0.0.1:5005")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    client = SpecialistClient(base_url=args.url, timeout_s=args.timeout,
                              on_status=_log_status)

    if args.all:
        cases = json.loads(TEST_CASES.read_text())
        submitted = 0
        correct = 0
        for case in cases:
            expected = case.get("expected_category")
            outcome = run_one(case["request"], client, expected)
            submitted += int(outcome.ok)
            # Tracked separately from ok: a ticket can submit successfully and
            # still be filed under the wrong category. This is the retrieval
            # baseline the real RAG pipeline has to beat.
            correct += int(bool(expected) and outcome.category == expected)
        print(f"\n{submitted}/{len(cases)} submitted   "
              f"{correct}/{len(cases)} categorised correctly")
        return

    if not args.request:
        parser.error("Provide a request, or use --all.")
    run_one(args.request, client)


if __name__ == "__main__":
    main()
