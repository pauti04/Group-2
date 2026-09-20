"""Turning a Specialist answer into the data the web form needs.

Owner: person 1 (Requester Agent) — this is step 1, item 7: "use the Specialist
Agent's response to determine what information to enter into the web
application". It stops exactly there. Actually driving the browser is item 8,
which lives behind the Submitter interface below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# KB category -> the <option> value in mock_support_app/index.html.
# Email and Security are deliberately absent: the dropdown has no option for
# them, even though the knowledge base documents both. See CONTRACTS.md.
CATEGORY_TO_OPTION = {
    "Account Access": "account_access",
    "Hardware": "hardware",
    "Software": "software",
    "Network": "network",
}


class PlanError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class FormPlan:
    """Exactly what goes into the three form fields. No browser concepts here."""

    issue: str          # -> #issue
    category_option: str  # -> #category (the <option> value)
    category_label: str   # what the confirmation screen should display
    resolution: str       # -> #resolution


@dataclass
class SubmissionResult:
    """What a Submitter reports back after the form round trip."""

    ticket_id: str
    category_shown: str
    resolution_shown: str


class Submitter(Protocol):
    """Step 1 item 8 lives behind this. Person 3 implements it with Playwright.

    Must raise PlanError("VERIFICATION_FAILED", ...) if the confirmation does
    not appear or does not match the plan.
    """

    def submit(self, plan: FormPlan) -> SubmissionResult: ...


def build_form_plan(user_text: str, result: dict) -> FormPlan:
    """Map a Contract 2 result onto the form's fields.

    Raises PlanError("UNMAPPABLE_CATEGORY") when the Specialist returns a
    category the form cannot express — we refuse rather than submit a ticket
    filed under the wrong category.
    """
    category = (result.get("category") or "").strip()
    resolution = (result.get("resolution") or "").strip()

    if not category or not resolution:
        raise PlanError(
            "NO_RELEVANT_CONTEXT",
            "The Specialist completed but returned no category or resolution.",
        )

    option = CATEGORY_TO_OPTION.get(category)
    if option is None:
        raise PlanError(
            "UNMAPPABLE_CATEGORY",
            f"The Specialist returned category {category!r}, which the ticket form has "
            f"no option for (available: {', '.join(sorted(CATEGORY_TO_OPTION))}). "
            f"Refusing to submit under a category the knowledge base did not support.",
        )

    return FormPlan(issue=user_text, category_option=option,
                    category_label=category, resolution=resolution)


class DryRunSubmitter:
    """Default submitter: records the plan without opening a browser.

    Lets steps 1 and 2 be demonstrated and tested before the Playwright work
    (steps 5-6) exists. Replace by passing a real Submitter to handle_request.
    """

    def __init__(self) -> None:
        self.last_plan: FormPlan | None = None

    def submit(self, plan: FormPlan) -> SubmissionResult:
        self.last_plan = plan
        return SubmissionResult(
            ticket_id="DRY-RUN",
            category_shown=plan.category_label,
            resolution_shown=plan.resolution,
        )
