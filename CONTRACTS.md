# Contracts — freeze these before anyone writes code

Two interfaces. Once these are agreed, all four tracks can be built in parallel
against stubs. **Do not change these without telling the whole team**, because
every track depends on both.

---

## Contract 1 — the A2A wire format

The Specialist Agent is an HTTP service. The Requester Agent is its only client.

### Submit a task

```
POST /tasks
Content-Type: application/json

{"question": "I forgot my password and cannot log into my account.",
 "needs": ["category", "resolution"]}
```

`question` is **the user's words and nothing else** — no instruction wrapper.
The Specialist uses it directly as the retrieval query, so any framing text
("Using the knowledge base, identify...") becomes noise in that query. We
learned this the hard way: an instruction wrapper pushed three of the five test
cases below the relevance threshold. Prompt framing belongs inside the RAG
layer, which knows how it is querying.

`needs` is optional and states what the Requester wants back; it defaults to
`["category", "resolution"]`. This is how the Requester expresses step 1 item 2
("determine what information it needs") without polluting retrieval.

Responds **immediately** (does not wait for RAG to finish):

```
201 Created
{"task_id": "b3f1c2de-...", "status": "submitted"}
```

### Poll a task

```
GET /tasks/<task_id>
```

```
200 OK
{"task_id": "...", "status": "working"}
```

...and once finished:

```
200 OK
{"task_id": "...", "status": "completed", "result": { ...Contract 2... }}
```

...or on failure:

```
200 OK
{"task_id": "...", "status": "failed",
 "error": {"code": "NO_RELEVANT_CONTEXT", "message": "..."}}
```

Unknown id:

```
404 Not Found
{"error": {"code": "UNKNOWN_TASK", "message": "..."}}
```

### Statuses

| status      | meaning                                              |
|-------------|------------------------------------------------------|
| `submitted` | accepted, not started                                 |
| `working`   | RAG pipeline is running                               |
| `completed` | `result` is present                                   |
| `failed`    | `error` is present, `result` is absent                |

`submitted` and `working` are both non-terminal; the Requester keeps polling.
`completed` and `failed` are terminal; the Requester stops.

### Error codes

| code                  | raised when                                          |
|-----------------------|------------------------------------------------------|
| `NO_RELEVANT_CONTEXT` | retrieval found nothing above the relevance threshold |
| `LLM_ERROR`           | the model call failed or returned unparseable output  |
| `UNKNOWN_TASK`        | polled task id does not exist                         |

---

## Contract 2 — the result payload

This is what the RAG pipeline returns and what Playwright consumes. It is the
single seam between person 2's work and person 3's work.

```json
{
  "category": "Account Access",
  "resolution": "Verify the user's identity and follow the approved password reset procedure.",
  "sources": ["password_reset.md", "account_access.md"],
  "confidence": 0.82
}
```

| field        | type       | rules                                                        |
|--------------|------------|--------------------------------------------------------------|
| `category`   | string     | Human-readable, exactly as the KB's `## Ticket Category` says |
| `resolution` | string     | 1–3 sentences, grounded in retrieved text, goes in the form   |
| `sources`    | string[]   | KB filenames actually used. Never empty on `completed`.       |
| `confidence` | float 0..1 | Retrieval/grading score. Used for logging and the report.     |

**`category` is the KB's wording, not the form's.** Mapping KB categories to the
`<select>` values is the Requester's job (see below) — the Specialist must not
know anything about the web form.

---

## The category mapping (Requester-side)

The mock app's dropdown has only four options:

| KB category      | form `<option>` value |
|------------------|------------------------|
| `Account Access` | `account_access`       |
| `Hardware`       | `hardware`             |
| `Software`       | `software`             |
| `Network`        | `network`              |
| `Email`          | **none — no option exists** |
| `Security`       | **none — no option exists** |

The knowledge base contains `email.md` and `security.md`, and `test_cases.json`
case #5 expects `Email`. There is deliberately no dropdown option for either.
When the Specialist returns one of these, the Requester must abort with
`UNMAPPABLE_CATEGORY` rather than guessing a wrong category. This is one of our
three documented failure scenarios.

---

## The Requester's own return type

Person 4's harness only ever calls one function, so persons 3 and 4 never edit
the same file:

```python
from requester.coordinator import handle_request

outcome = handle_request("My laptop won't connect to Wi-Fi.")
```

```python
@dataclass
class Outcome:
    ok: bool
    ticket_id: str | None       # 5-digit id from the confirmation screen
    category: str | None        # KB category that was used
    resolution: str | None
    sources: list[str]
    error_code: str | None      # None when ok
    error_message: str | None
    elapsed_ms: int
```

`error_code` is one of the A2A codes above, plus these Requester-side codes:

| code                   | raised when                                        |
|------------------------|-----------------------------------------------------|
| `TIMEOUT`              | polling exceeded the deadline                       |
| `UNMAPPABLE_CATEGORY`  | KB category has no dropdown option                  |
| `VERIFICATION_FAILED`  | form submitted but the confirmation did not match   |
| `SPECIALIST_UNREACHABLE` | the server is not running                         |
