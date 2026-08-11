# Decisions

This document records key design decisions for the Hanik improvement loop,
the reasoning behind them, and the alternatives that were considered and
rejected. It complements `HANIK_SPEC.md` (what Hanik must do) and
`SECURITY.md` (how it is kept safe).

## 1. Offline, rule-based evaluation instead of an LLM call

**Decision:** `src/hanik_loop.py` evaluates the previous iteration and
generates recommendations using a deterministic, rule-based algorithm. It
does not call any LLM or external API.

**Why:** The original request asked for a loop that repeats "continuously"
after each iteration completes. An LLM-backed loop with no bound would
introduce unpredictable cost, unpredictable output, and a much larger
security surface (prompt injection, data exfiltration, provider lock-in)
for an unattended, potentially long-running process. A deterministic,
offline evaluator can be fully unit-tested, has no per-run cost, requires
no provider credentials, and is trivially reviewable by a human.

**Alternative considered:** Wire the loop directly to an LLM provider
(e.g. via an API key secret) to produce genuinely novel critiques each
iteration. Rejected for the first iteration because it would require
provider credentials (violating "do not hard-code secrets or external
provider credentials" and needing careful secret management), would make
tests non-deterministic or require mocking, and would significantly
expand the security review needed before running unattended. This remains
a documented **hypothesis** for a future iteration once the corresponding
`SECURITY.md` controls (rate limits, cost caps, injection defenses) are
designed and reviewed.

## 2. Bounded iterations, not an unbounded loop or daemon

**Decision:** Each GitHub Actions run performs exactly **one** iteration
and then exits. Continuing to the next iteration is an explicit,
opt-in `repository_dispatch` triggered only on success, only when
`HANIK_CONTINUOUS=true`, and only up to `HANIK_MAX_ITERATIONS` (checked
both by the workflow and independently inside `run_iteration()`, which
raises `MaxIterationsReachedError` once the bound is reached).

**Why:** The user asked for the loop to restart after each task
completes rather than run on a fixed schedule. A truly unbounded,
self-perpetuating automation is difficult to safely stop, easy to run
away with cost/resources, and conflicts with keeping a human able to
intervene at any time (`HANIK_SPEC.md` §3 Human Control). A bounded,
iteration-per-run design keeps every single execution short, inspectable,
and cancelable, while still satisfying the "continues after completion"
requirement within safe limits.

**Alternative considered:** A long-lived runner process (e.g. a
self-hosted daemon or a workflow with a `while true` loop inside one job)
that keeps iterating without exiting. Rejected because GitHub Actions job
timeouts, billing models, and operational risk make an indefinitely
running job an anti-pattern; it also makes "stop the loop" much harder
than "don't trigger the next dispatch."

## 3. Separate `HANIK_DISPATCH_TOKEN` instead of the default `GITHUB_TOKEN`

**Decision:** The completion-triggered `repository_dispatch` call uses a
dedicated `HANIK_DISPATCH_TOKEN` secret, not the workflow's own
`GITHUB_TOKEN`.

**Why:** GitHub Actions deliberately does not let events created with the
default `GITHUB_TOKEN` trigger further workflow runs, as an anti-recursion
safeguard. Using a separate token is the officially supported way to
intentionally chain workflow runs. Keeping it separate from `GITHUB_TOKEN`
also means it can be independently scoped (ideally to just
`repository_dispatch` on this one repository) and independently revoked
as an emergency stop, without affecting the rest of the workflow's ability
to check out code, run tests, and open pull requests.

**Alternative considered:** Grant `GITHUB_TOKEN` elevated permissions and
attempt to force recursive triggering. Rejected: this fights an
intentional platform safeguard, would likely require unsafe workarounds,
and would remove the clean "revoke one secret to stop everything"
emergency shutdown story described in `SECURITY.md`.

## 4. Atomic state writes via temp-file + `os.replace`

**Decision:** `save_state_atomic()` writes to a temporary file in the same
directory as `state/state.json` and then calls `os.replace()`, rather than
writing directly to the target path.

**Why:** `os.replace()` is atomic on both POSIX and Windows: a reader can
never observe a partially-written file. This protects against corruption
if the process is killed mid-write (e.g. workflow timeout, cancellation)
and is a well-established pattern for crash-safe file updates.

**Alternative considered:** Write directly to `state/state.json` with a
single `open(...).write(...)`. Rejected because a crash between opening
the file (which truncates it) and finishing the write would leave
`state/state.json` corrupted, which the loop would then have to recover
from anyway -- better to avoid the corruption in the first place.

## 5. Scores are capped below 1.0

**Decision:** `MAX_SCORE = 0.95`, strictly less than a "perfect" `1.0`.

**Why:** This is a deliberate signal that the evaluation is never treated
as "done" or "complete" -- there is always room for renewed critical
evaluation in the next iteration, consistent with `HANIK_SPEC.md` §7's
requirement that each iteration must critically re-evaluate rather than
assume prior success is final.

## 6. Corrupted or malformed state resets to a fresh empty state

**Decision:** `load_state()` catches JSON decode errors and structural
validation failures (wrong types, missing keys) and returns a fresh empty
state (`{"iteration": 0, "history": []}`) instead of raising.

**Why:** The loop must always be able to make forward progress even if
`state/state.json` was hand-edited incorrectly, corrupted by a prior
crashed run (mitigated by atomic writes, but defense in depth still
matters), or manipulated. Silently resetting to iteration 0 is safer than
crashing the workflow, and the reset is visible in the resulting report
(iteration counter restarts) so it is not hidden from human reviewers.

**Alternative considered:** Fail loudly and stop the workflow on any state
corruption. Rejected as the first line of defense because it would turn a
recoverable data issue into a hard outage requiring manual intervention;
however, reviewers should still notice an unexpected iteration-counter
reset in the generated report and investigate why the state file was
corrupted.
