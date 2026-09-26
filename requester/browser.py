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
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError #for step 7
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
        with sync_playwright() as playwright: #according to https://playwright.dev/python/docs/api/class-playwright
            #https://playwright.dev/python/docs/api/class-browsertype
            browser = playwright.chromium.launch(headless=self.headless, slow_mo=self.slow_mo_ms) #1. sync_playwright() -> chromium.launch(headless=...) -> new_page() -> goto(APP_URL)
            try:
                page = browser.new_page()
                #https://playwright.dev/docs/api/class-page
                page.goto(APP_URL, wait_until="domcontentloaded")
                page.fill("#issue", plan.issue)
                page.select_option('#category', plan.category_option)
                page.fill("#resolution", plan.resolution)
                page.click("#submit-ticket"); #2. fill #issue, select_option #category, fill #resolution, click #submit-ticket
                try:
                    page.wait_for_selector("#confirmation:not(.hidden)", timeout=self.timeout_ms) #3. wait_for_selector("#confirmation:not(.hidden)") with a timeout
                except PlaywrightTimeoutError:
                    raise PlanError("VERIFICATION_FAILED", page.locator("#error").inner_text() or "The confirmation message did not appear.")

                #Read the three confirmation fields into a SubmissionResult and return it.
                ticket_id = (page.locator("#ticket-id").inner_text().strip())
                category_shown = (page.locator("#ticket-category").inner_text().strip())
                resolution_shown = (page.locator("#ticket-resolution").inner_text().strip())

                #The coordinator already re-checks them against the plan, so you do not need to compare them here — but do sanity-check that #ticket-id is 5 digits.
                if not re.fullmatch(r"\d{5}", ticket_id):
                    raise PlanError("VERIFICATION_FAILED", f"Invalid ticket ID returned by application: {ticket_id}")

                return SubmissionResult(
                    ticket_id = ticket_id,
                    category_shown = category_shown,
                    resolution_shown = resolution_shown
                )
            finally:
                #Always close the browser (try/finally).
                browser.close()
