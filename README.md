# Group 2 — Multi-Agent AI Support System

Two cooperating agents. A **Requester Agent** takes a user's support request,
asks a **Specialist Agent** over an A2A-style HTTP protocol what ticket category
and resolution apply, and then fills and submits the mock support ticket form
with that answer. The Specialist answers from the provided knowledge base using
RAG.

```
User request
   -> Requester Agent      (requester/coordinator.py)
   -> A2A: POST /tasks     (requester/a2a_client.py -> specialist/server.py)
   -> Specialist Agent     (specialist/server.py, specialist/tasks.py)
   -> RAG over knowledge_base/   (rag/pipeline.py, rag/retrieval.py)
   -> result: category + resolution + sources
   -> Requester Agent      decides what goes in each form field
   -> Playwright           (requester/browser.py)
   -> Verification         confirmation must match what the Specialist said
```

## Status

| Assignment step | Where | State |
|---|---|---|
| 1. Requester Agent | `requester/coordinator.py`, `a2a_client.py`, `form_plan.py`, `cli.py` | **done** |
| 2. Specialist Agent | `specialist/server.py`, `specialist/tasks.py` | **done** |
| 3. A2A protocol | `CONTRACTS.md`, `specialist/tasks.py`, `specialist/server.py`, `requester/a2a_client.py` | **done** |
| 4. RAG + advanced technique | `rag/retrieval.py` | **skeleton** — running on `rag/stub.py` |
| 5-6. Playwright | `requester/browser.py` | **skeleton** — running on `DryRunSubmitter` |
| 7. Timeout / failure handling | partly done, see below | needs the three scenarios written up |
| Harness, report, video | `harness/`, `docs/` | not started |

The system runs end to end today on a deterministic stub retriever and a dry-run
submitter, so steps 4 and 5-6 can be built independently without blocking anyone.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install flask requests          # enough for steps 1-2
cp .env.example .env                # no API key needed for the stub
```

## Run it

Two terminals. First the Specialist:

```bash
python -m specialist.server --delay 1
```

`--delay` keeps each task in the real `working` state before it calls RAG, which
makes the `submitted -> working -> completed` transitions visible while polling.
Then the Requester:

```bash
python -m requester.cli "I forgot my password and cannot log into my account."
python -m requester.cli --all       # all five cases from test_cases.json
```

Current baseline with the stub retriever: **4/5 submitted, 4/5 categorised
correctly.**

## Step 3 — A2A protocol

The Requester and Specialist use an asynchronous HTTP task protocol. A
`POST /tasks` submission returns immediately with `201 Created` and the
acceptance payload `{ "task_id": "<UUID>", "status": "submitted" }`; RAG work
continues on a background thread. The Requester then polls
`GET /tasks/<task_id>` until it receives a terminal state.

```
submitted --background worker starts--> working --RAG succeeds--> completed
                                           \
                                            --RAG fails-----> failed
```

`completed` responses contain the Contract 2 `result` object. `failed`
responses contain only an `error` object with a stable `code` and explanatory
`message`; they never include a result. The Requester stops polling on either
terminal state and turns a failed response into an `A2AError`. An unknown task
ID returns `404` with `UNKNOWN_TASK`, and the Requester also reports `TIMEOUT`
or `SPECIALIST_UNREACHABLE` when polling cannot complete. See
[`CONTRACTS.md`](CONTRACTS.md) for the full request and response shapes.

## Step 4 — RAG pipeline
The real pipeline (rag/retrieval.py) replaces the day-one keyword-overlap stub (rag/stub.py, kept for comparison) with fusion retrieval: BM25 and dense (sentence-transformers + FAISS) rankings over section-level chunks (Description/Symptoms/When to Use only — the parts of each doc that describe the problem, not the fix), combined with Reciprocal Rank Fusion. Fused candidates are graded for relevance by an LLM (rag/llm.py, via Groq) before generation, so the pipeline honestly raises NO_RELEVANT_CONTEXT when nothing retrieved actually answers the question rather than letting the model improvise. category is always read verbatim from the winning document's own Ticket Category section, never generated freeform, so it matches the Requester's category mapping exactly.

This fixes the stub's known weakness: "My laptop won't connect to Wi-Fi" was classified Hardware because keyword overlap on "laptop" outscored network.md, which never mentions laptops. BM25 now scores network.md's Symptoms chunk on "Wi-Fi" directly, and the fused result is correctly Network. See rag/retrieval.py's module docstring for the full rationale, and the report for the before/after comparison against test_cases.json.

The index (embeddings + BM25 corpus) is built once per server process — protected by a lock so concurrent requests can't trigger redundant rebuilds — and cached to disk, keyed by a hash of knowledge_base/'s contents, so edits to the KB auto-invalidate the cache.

Known behaviour worth keeping
"My company email is not synchronizing" retrieves correctly (category: Email) but fails downstream with UNMAPPABLE_CATEGORY. Not a bug. The knowledge base documents Email and Security, but the ticket form's dropdown has only Account Access / Hardware / Software / Network. Rather than file the ticket under a wrong category, the Requester refuses. This is one of our documented failure scenarios (step 7), and it's why the ceiling is 4/5 submitted even with a fully correct RAG pipeline.

Working on this repo
Read CONTRACTS.md first. It defines the two interfaces — the A2A wire format and the result payload — that everything else is built against. If you need to change either one, tell the whole team, because all four tracks depend on them.

Do not commit .env, any API key, or rag/.index_cache.pkl.

## Known behaviour worth keeping

**"My laptop won't connect to Wi-Fi" is classified `Hardware`, not `Network`.**
The stub scores keyword overlap, and "laptop" pulls `hardware.md` ahead of
`network.md`. This is the exact weakness the advanced RAG technique is meant to
fix — see the rationale in `rag/retrieval.py`. Beat 4/5 and put the before/after
in the report.

**"My company email is not synchronizing" fails with `UNMAPPABLE_CATEGORY`.**
Not a bug. The knowledge base documents Email and Security, but the ticket
form's dropdown has only Account Access / Hardware / Software / Network. Rather
than file the ticket under a wrong category, the Requester refuses. This is one
of our documented failure scenarios (step 7).

## Working on this repo

Read `CONTRACTS.md` first. It defines the two interfaces — the A2A wire format
and the result payload — that everything else is built against. If you need to
change either one, tell the whole team, because all four tracks depend on them.

Do not commit `.env` or any API key.
