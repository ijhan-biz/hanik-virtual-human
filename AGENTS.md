# AGENTS.md

You are starting a session with no memory of the previous one. This file and
`state/next-session.md` are the entire handover. Read both before touching
anything else.

## The loop

This repository builds **Hanik**, a virtual human. The artifact being improved
is `hanik/` — the persona, its policies, and its benchmarks. Everything else
exists to measure that artifact and to hand the next session a task.

One iteration is one session:

1. A session reads `state/next-session.md` and picks the top open task.
2. The session implements that task for real, in `hanik/`, `src/`, `tests/`, or
   `.github/workflows/`.
3. The session runs the loop, which re-measures the repository from scratch,
   writes `reports/iteration-NNNN.html` plus its JSON companion, updates
   `state/state.json`, and rewrites `state/next-session.md`.
4. The change is delivered as a pull request for human review.
5. If the evidence actually changed, the workflow asks for one more iteration —
   a new run, a new implementation session. If every check passes, the next
   session must add a substantive check for a missing capability instead of
   ending the chain.

Scores are not opinions. Each criterion in `HANIK_SPEC.md` is backed by checks
in `src/checks.py` that read files on disk; a criterion's score is the share of
its checks that pass. Nothing improves unless an artifact changes.

## What a session must do

1. **Read the brief.** `state/next-session.md` lists the failing checks in
   priority order, with the evidence for each failure, the remediation, and the
   files to touch.
2. **Pick exactly one task.** The first one, unless you have a stated reason to
   prefer another. One task done properly beats five done superficially.
3. **Implement it in the artifact.** Write the persona section, the policy, the
   benchmark scenario, or the test that the check is asking for. Write it as if
   a person will rely on it, because the check only measures that it exists and
   is substantive — it cannot measure whether it is any good. That part is on
   you. The automated implementation session must leave a repository change;
   an unchanged checkout is a failed iteration, not progress.
4. **Verify.** `python3 -m pip install -r requirements-dev.txt` then
   `python3 -m pytest tests/ -v`.
5. **Run the loop last.** `python3 -m src.hanik_loop`. This regenerates the
   report, the index, the state, and the brief for the session after you.
   Running it before your change means you hand the next session stale
   information.
6. **Open a pull request.** Never merge it yourself.

## Rules

- **Change the artifact, not the check.** Editing `src/checks.py` to make a
  failing check pass without building the capability is the one failure this
  loop cannot detect on its own. It is exactly how the previous scoring model
  went wrong: scores climbed to 0.90 across 250 iterations while nothing about
  Hanik was ever built.
- **Never fabricate evidence.** Do not write a file whose only purpose is to
  satisfy a string match. If a check is measuring the wrong thing, say so in
  the pull request and change the check deliberately, with the reasoning
  recorded in `DECISIONS.md`.
- **When the backlog is empty, raise the bar.** All checks passing means the
  standard is too low, not that Hanik is finished. Add a check for a capability
  Hanik genuinely lacks, with a concrete `remediation` and `targets`, and let
  the next iteration fail it.
- **When the loop reports stagnation, stop.** Repeated identical evidence means
  re-running changes nothing. Implement something or escalate to a human;
  the workflow will stop the chain on its own after
  `HANIK_STAGNATION_LIMIT` no-progress iterations.
- **Stay offline and inert.** `src/` must not import networking modules and
  must not execute anything it generates; both are enforced by AST scans in
  `safety.no_network_imports` and `safety.no_dynamic_execution`.
- **No secrets, ever**, in code, state, or reports. See `SECURITY.md`.

## Where things are

| Path | Purpose |
| --- | --- |
| `hanik/persona.md` | The virtual human: identity, voice, limits, escalation |
| `hanik/policies/` | Safety and privacy policies the persona is bound by |
| `hanik/benchmarks/` | Behavioural scenarios used to catch regressions |
| `src/checks.py` | The evidence checks; failing ones are the backlog |
| `src/hanik_loop.py` | Orchestration, scoring, stagnation detection |
| `src/reporting.py` | HTML report, JSON companion, index, session brief |
| `src/state.py` | Atomic state writes, pruning, lossless archive |
| `state/next-session.md` | Your brief. Start here |
| `reports/index.html` | Every iteration, newest first |
