"""Playwright submitter — steps 5 and 6 of the assignment.

Owner: person 3. NOT YET IMPLEMENTED.

This is the only place Playwright should appear. Implement the Submitter
protocol from requester/form_plan.py and the coordinator will pick it up with
no changes anywhere else:

    from requester.browser import PlaywrightSubmitter
    outcome = handle_request(text, submitter=PlaywrightSubmitter())

=============================================================================
What the page gives you (from mock_support_app/index.html and script.js)
=============================================================================
The app is a static file with no backend, so load it over file:// — APP_URL
below is already built for you.

    #issue          textarea   <- plan.issue
    #category       select     <- plan.category_option (the <option> VALUE)
    #resolution     textarea   <- plan.resolution
    #submit-ticket  button     submit

On success the script removes the `hidden` class from #confirmation and fills:

    #ticket-id          5-digit number, e.g. "48213"
    #ticket-category    the human-readable label, e.g. "Account Access"
    #ticket-resolution  the resolution text, echoed verbatim

On any empty field it instead reveals #error with
"Please fill out all fields before submitting."

=============================================================================
TODO (person 3)
=============================================================================
1. sync_playwright() -> chromium.launch(headless=...) -> new_page() -> goto(APP_URL)
2. fill #issue, select_option #category, fill #resolution, click #submit-ticket
3. wait_for_selector("#confirmation:not(.hidden)") with a timeout
4. If it never appears, read #error and raise
   PlanError("VERIFICATION_FAILED", <what the page said>)
5. Read the three confirmation fields into a SubmissionResult and return it.
   The coordinator already re-checks them against the plan, so you do not need
   to compare them here — but do sanity-check that #ticket-id is 5 digits.
6. Always close the browser (try/finally).
7. Add a headless=False / slow_mo option — the demo video needs a visible run.
"""

from __future__ import annotations

from pathlib import Path

from requester.form_plan import FormPlan, PlanError, SubmissionResult

APP_PATH = Path(__file__).resolve().parent.parent / "mock_support_app" / "index.html"
APP_URL = APP_PATH.as_uri()


class PlaywrightSubmitter:
    def __init__(self, *, headless: bool = True, slow_mo_ms: int = 0,
                 timeout_ms: int = 5000) -> None:
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self.timeout_ms = timeout_ms

    def submit(self, plan: FormPlan) -> SubmissionResult:
        raise PlanError(
            "VERIFICATION_FAILED",
            "PlaywrightSubmitter is not implemented yet (steps 5-6). "
            "Run with the default DryRunSubmitter until it is.",
        )
