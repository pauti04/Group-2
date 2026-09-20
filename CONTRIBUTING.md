# Working on this repo

No branch protection is configured, so `main` is only as clean as we keep it.
Everything below is convention, not enforcement.

## Before you write any code

Read [`CONTRACTS.md`](CONTRACTS.md). It defines the two interfaces every track
is built against: the A2A wire format, and the result payload the Specialist
returns. If your work needs either one changed, say so in the group chat before
you change it — all four tracks break together.

## The loop

1. Branch off `main`. Name it after your step, e.g. `step-4-rag`,
   `step-5-playwright`, `step-7-error-handling`.
2. Commit as you go. Small commits with real messages beat one giant "final"
   commit — part of the grade is team participation, and the git history is the
   evidence.
3. Open a PR. Say what you changed and how to run it.
4. Get one teammate to review it. Anyone except you.
5. Merge, and delete the branch.

Do not push to `main` directly. Nothing stops you; don't anyway.

## Review each other's PRs

Each of us should review at least one PR that isn't our own. A review can be
short — "pulled it, ran `--all`, 5/5, looks good" is a real review. What matters
is that someone other than the author ran the code before it hit `main`.

## Who owns what

| Step | Files | Owner |
|---|---|---|
| 1-2. The two agents | `requester/`, `specialist/` | done |
| 3. A2A protocol | `CONTRACTS.md` + the two above | shared |
| 4. RAG + advanced technique | `rag/retrieval.py` | |
| 5-6. Playwright | `requester/browser.py` | |
| 7. Timeout / failure handling | `harness/` | |
| Report + video | `docs/` | |

Fill in the names. Two people editing the same file is where a group project of
four actually goes wrong, so if you need to touch a file outside your row, say
something first.

## Never commit

- `.env`, or an API key in any file. `.env.example` is the template; it stays
  empty.
- `.venv/`, `__pycache__/`, or a FAISS index. All gitignored already.

If a key does get committed, tell the group immediately and rotate it — deleting
it in a later commit does not remove it from the history.
