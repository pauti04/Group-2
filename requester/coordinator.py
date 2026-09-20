"""Requester Agent — coordinates the whole workflow.

Owner: person 1. This is step 1 of the assignment, all nine items:

    1. receive a request                     -> handle_request(user_text)
    2. decide what it needs                  -> build_question()
    3. create a task                         -> SpecialistClient.submit()
    4. send it over A2A                      -> POST /tasks
    5. get an immediate ack with a task id   -> {"task_id", "submitted"}
    6. poll for the result                   -> SpecialistClient.poll_until_done()
    7. decide what goes in the form          -> build_form_plan()
    8. drive the browser                     -> Submitter (person 3's Playwright)
    9. verify the expected result            -> Submitter + _verify()

The harness (person 4) calls exactly one function from here, so no one else
needs to edit this file:

    outcome = handle_request("My laptop won't connect to Wi-Fi.")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from requester.a2a_client import A2AError, SpecialistClient
from requester.form_plan import (
    DryRunSubmitter,
    FormPlan,
    PlanError,
    SubmissionResult,
    Submitter,
    build_form_plan,
)


@dataclass
class Outcome:
    ok: bool
    ticket_id: str | None = None
    category: str | None = None
    resolution: str | None = None
    sources: list[str] = field(default_factory=list)
    confidence: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    elapsed_ms: int = 0
    polls: int = 0

    def summary(self) -> str:
        if self.ok:
            return (f"OK  ticket={self.ticket_id}  category={self.category}  "
                    f"sources={','.join(self.sources)}  {self.elapsed_ms}ms")
        return f"FAIL [{self.error_code}] {self.error_message}"


# Step 1 item 2 — what the Requester knows it needs from the Specialist. It
# needs exactly the two things the ticket form cannot be filled without, and it
# does not try to work either of them out itself: that is the Specialist's job,
# grounded in the knowledge base.
NEEDS = ["category", "resolution"]


def build_question(user_text: str) -> str:
    """Normalize the user's request into the question sent over A2A.

    Deliberately the issue text and nothing else. An earlier version wrapped it
    in instruction boilerplate ("Using the support knowledge base, identify...")
    and that wording leaked into the retrieval query, diluting the keyword
    signal enough to push three of the five test cases below the relevance
    threshold. Prompt framing belongs to the RAG layer, which knows how it is
    querying; the wire carries the user's words plus NEEDS.
    """
    return user_text.strip()


def handle_request(user_text: str, *, client: SpecialistClient | None = None,
                   submitter: Submitter | None = None) -> Outcome:
    """Run the full workflow. Never raises — every failure becomes an Outcome."""
    started = time.monotonic()
    client = client or SpecialistClient()
    submitter = submitter or DryRunSubmitter()

    def finish(outcome: Outcome) -> Outcome:
        outcome.elapsed_ms = int((time.monotonic() - started) * 1000)
        return outcome

    # --- Items 2-6: ask the Specialist over A2A -----------------------------
    try:
        task = client.ask(build_question(user_text), needs=NEEDS)
    except A2AError as exc:
        return finish(Outcome(ok=False, error_code=exc.code, error_message=exc.message))

    result = task.result
    sources = result.get("sources", [])
    confidence = result.get("confidence")

    # --- Item 7: decide what to enter into the form -------------------------
    try:
        plan = build_form_plan(user_text, result)
    except PlanError as exc:
        return finish(Outcome(
            ok=False, category=result.get("category"), resolution=result.get("resolution"),
            sources=sources, confidence=confidence,
            error_code=exc.code, error_message=exc.message, polls=task.polls,
        ))

    # --- Items 8-9: submit and verify ---------------------------------------
    try:
        submission = submitter.submit(plan)
        _verify(plan, submission)
    except PlanError as exc:
        return finish(Outcome(
            ok=False, category=plan.category_label, resolution=plan.resolution,
            sources=sources, confidence=confidence,
            error_code=exc.code, error_message=exc.message, polls=task.polls,
        ))

    return finish(Outcome(
        ok=True, ticket_id=submission.ticket_id, category=plan.category_label,
        resolution=plan.resolution, sources=sources, confidence=confidence,
        polls=task.polls,
    ))


def _verify(plan: FormPlan, submission: SubmissionResult) -> None:
    """Step 1 item 9 — a confirmation box alone is not proof.

    Check that what the app echoed back is what the Specialist actually told us,
    so a ticket filed with the wrong category cannot be reported as success.
    """
    if submission.category_shown != plan.category_label:
        raise PlanError(
            "VERIFICATION_FAILED",
            f"Confirmation shows category {submission.category_shown!r} but the "
            f"Specialist said {plan.category_label!r}.",
        )
    if submission.resolution_shown.strip() != plan.resolution.strip():
        raise PlanError(
            "VERIFICATION_FAILED",
            "Confirmation resolution text does not match what the Specialist returned.",
        )
