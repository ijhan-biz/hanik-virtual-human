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

## 2. One iteration per run, one session per iteration

**Decision:** Each GitHub Actions run performs exactly one iteration and then
exits. A successful run requests the next iteration through
`repository_dispatch` only when the loop itself reports `should_continue`. The
persisted iteration number is cumulative across runs.

**Why:** Each iteration is meant to be a fresh session with no memory of the
previous one — that is the whole point of writing `state/next-session.md` to
disk. Batching many iterations into one run defeats this: the later iterations
inherit the earlier ones' context, and a single run becomes long, hard to
cancel, and hard to review. One iteration per run keeps every execution short,
inspectable, and cancelable, gives each iteration a clean runner, and makes
"stop the loop" as simple as not dispatching the next one.

**Alternative considered:** A long-lived runner process (e.g. a self-hosted
daemon or a workflow with a `while true` loop inside one job) that keeps
iterating without exiting. Rejected because GitHub Actions job timeouts,
billing models, and operational risk make an indefinitely running job an
anti-pattern; it also makes "stop the loop" much harder than "don't trigger the
next dispatch."

**Superseded:** An earlier version ran 50 iterations per batch
(`HANIK_BATCH_SIZE`). That variable no longer exists.

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

## 5. No score cap, because a perfect score is a bar problem

**Decision:** Scores are not capped. A criterion whose checks all pass scores
`1.0`, and the report and session brief respond by demanding a new check rather
than declaring the criterion finished.

**Why:** An artificial ceiling (the earlier `MAX_SCORE = 0.95`) was an attempt
to signal "never done" through arithmetic. It does not work: a permanent 0.05
gap that no possible action can close is indistinguishable from noise, and it
makes the score stop meaning "share of evidence satisfied." Under evidence-based
scoring, `1.0` is a real and legible statement — every check currently written
passes. The correct response is to raise the bar, and the loop says so
explicitly in that state, which is a demand for work rather than a number that
can never be reached.

**Alternative considered:** Keep the cap and treat the residual as a reminder.
Rejected because a reminder nobody can act on is noise, and because a capped
score cannot be interpreted as a coverage ratio.

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

## 7. Evidence-based scoring replaced self-congratulating scoring

**Decision:** A criterion's score is the share of its checks that pass, where
each check in `src/checks.py` reads a file, parses an AST, or scans generated
output. Nothing is carried forward between iterations except the iteration
counter and history.

**Why:** The original design scored a criterion higher because the *previous
iteration had recommended improving it*:

```python
if criterion in previous_recommended:
    base += IMPROVEMENT_STEP
```

A recommendation was emitted for any criterion below target, so every criterion
climbed 0.40 → 0.90 in five iterations regardless of whether anything changed,
and then froze. By iteration 50 the loop had "achieved" its target on all eight
criteria; it then produced 200 more iterations of an identical report. Nothing
about Hanik was ever built, because there was no Hanik — the loop only ever
evaluated itself.

That is the failure mode this repository now exists to avoid, and it is worth
stating plainly: a metric that improves because you intended to improve it is
not a metric. `reports/iteration-0001.html` through `-0250.html` are kept as the
evidence of what that looks like.

**Alternative considered:** Keep the incremental model but require a commit
touching relevant files before granting the increment. Rejected as a weaker
version of the same idea: it measures activity rather than result, and a commit
touching a file proves nothing about what the file now says.

## 8. Failing checks are the backlog

**Decision:** There is no task list. Every check carries a `remediation` string
and a `targets` tuple, and the set of failing checks *is* the work queue. The
session brief is generated by sorting failing checks by criterion weight.

**Why:** A hand-maintained backlog drifts away from the evaluation, and then
either the loop works on tasks that no longer matter or it reports success on
criteria nobody is working on. Deriving tasks from failures makes drift
impossible: a task exists exactly as long as the evidence for it is missing, and
disappears the moment the evidence appears. It also means completion is defined
by the artifact rather than by an agent's assertion that it finished.

**Consequence:** The initial three checks — a second-language persona, a
red-team suite, and benchmark scenarios — were intentionally left as a real
starting backlog. Once those artifacts were implemented, the next iteration
raised the bar with a new Korean safety-policy check rather than declaring
Hanik finished.

**Risk:** The obvious way to make a check pass is to weaken the check. The loop
cannot detect this about itself, since a weakened check reports a true pass. The
only mitigations are stating the rule in `AGENTS.md`, repeating it in every
generated brief, and human pull-request review — which is a large part of why
nothing merges itself.

## 9. Stagnation detection, not an iteration budget, controls the loop

**Decision:** Each iteration records an evidence signature — the pass/fail
outcome of every check, sorted by check ID. If the signature matches the
previous iteration, the run counts as no progress, and after
`HANIK_STAGNATION_LIMIT` consecutive no-progress iterations (default 2) the
chain stops. `HANIK_MAX_ITERATIONS` remains as a safety ceiling but is set to
10 000 rather than 50.

**Why:** The old `DEFAULT_MAX_ITERATIONS = 50` conflated two unrelated things:
"stop when this is no longer productive" and "never exceed this count." It also
had a latent bug — with the counter already at 250, the loop would have refused
to run at all. Stagnation is the correct control because it measures the thing
that actually matters: if the evidence did not move, running again cannot help,
and the loop should say so instead of producing another identical report. The
ceiling is retained purely as a backstop against a pathological oscillation
between two states.

**Design detail:** The signature deliberately ignores evidence wording and check
ordering, tracking only outcomes. Otherwise a reworded remediation string would
register as progress. There is a test for exactly this.

## 10. The artifact lives in `hanik/`, separate from the loop

**Decision:** Hanik itself — persona, policies, benchmarks — is a directory of
Markdown, versioned alongside but strictly separate from `src/`.

**Why:** The loop and the thing being improved must be distinguishable, or the
loop starts measuring itself. A file layout enforces that better than a
convention: `src/checks.py` reads `hanik/` and the reports it generates, and
"improving Hanik" means editing files under `hanik/`. Markdown was chosen over a
structured format because the persona is read by humans during review and by
agents as context, and both are better served by prose with headings than by a
schema. The checks parse headings, bullet counts, and exact sentences, which is
enough structure to be verifiable without making the artifact unreadable.

**Alternative considered:** Model the persona as YAML or JSON with a schema.
Rejected because it optimizes for the checker at the expense of every human and
agent that has to read it, and because schema conformance is a weaker signal
than the presence of four worked example exchanges.

## 11. Raise the bar with translated safety policy

**Decision:** After implementing the initial backlog, add
`safety.multilingual_policy` for `hanik/policies/safety.ko.md`. It requires
Korean refusal rules, at least five harm categories, and a human-escalation
section. The artifact is intentionally the next open task, so the automatic
chain has useful work instead of stopping at an artificial 1.0.

**Why:** `hanik/persona.ko.md` makes Korean identity and examples concrete, but
an English-only safety policy still leaves a language-specific gap in the
capability Hanik promises. A translated policy is a substantive safety
improvement, not a string-match exercise: it must preserve refusal and
escalation behaviour for users who never read the English policy. The check
also demonstrates the required empty-backlog behaviour — completion raises
the bar with a new, actionable task.

**Alternative considered:** Treat the Korean persona as sufficient and let the
loop stop with all existing checks passing. Rejected because a perfect score
would then reward language coverage without equivalent safety coverage, and the
repository's contract explicitly says an empty backlog must produce a harder
check.

## 12. Checks must test meaning, not only document shape

**Decision:** Strengthen `safety.multilingual_policy` so it checks the content
of the Korean refusal, harm, and handoff sections: role-play must not bypass a
refusal, self-harm must be named, and emergency/crisis escalation must be
present. Add a regression test proving headings and five arbitrary bullets do
not pass.

**Why:** A critical review of the previous session found that its new check
would pass a policy made only of headings plus five meaningless bullets. That
would increase the score without delivering a safety capability — the exact
failure mode this repository was redesigned to prevent. Structural checks are
useful as a first gate, but safety checks must also verify the concrete concepts
the policy claims to cover.

The same review found that Korean identity and safety coverage still had a
privacy-language gap. `privacy.multilingual_policy` therefore becomes the next
task after the Korean safety policy, requiring Korean collection, retention, and
deletion guidance rather than silently treating English documentation as
translated.

**Alternative considered:** Accept the heading/count check and rely on human
review to notice empty content. Rejected because the automated loop would
already have reported a passing score and could have stopped before a reviewer
looked at the artifact.
