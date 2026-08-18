# hanik-virtual-human

An automated improvement loop for **Hanik**, a virtual human. Each iteration
measures Hanik against explicit, file-backed evidence, writes a report, and
hands the next session a concrete task. The evaluator runs entirely offline:
no LLM provider, no network access, and no credentials. The workflow's
separate implementation phase uses Copilot CLI on an ephemeral runner and
passes its changes through tests and human review.

The thing being improved is `hanik/` — the persona, its policies, and its
benchmarks. Everything else exists to measure that artifact and to keep a
human in control of what lands.

## How the loop works

One run of the loop is one iteration, and one iteration is one fresh session:

1. The session reads `state/next-session.md` — the brief left by the previous
   iteration, listing the failing checks in priority order.
2. It implements **one** task for real, in `hanik/`, `src/`, `tests/`, or the
   workflow.
3. It runs `python3 -m src.hanik_loop`, which re-measures the repository from
   scratch and regenerates the report, the index, the state, and the brief.
4. The change is delivered as a pull request for human review.
5. If the evidence actually changed, the workflow dispatches one more
   iteration — a new run, a new implementation session. If every check passes,
   that session must add a substantive check for a missing capability.

The full contract each session follows is in [`AGENTS.md`](AGENTS.md).

## Scores are evidence, not opinion

Each of the eight criteria in [`HANIK_SPEC.md`](HANIK_SPEC.md) — `identity`,
`transparency`, `human_control`, `safety`, `privacy`, `memory`, `evaluation`,
`oversight` — is backed by checks in `src/checks.py` that read files on disk:
persona sections, policy headings, AST scans of `src/`, PII scans of generated
output, workflow permissions, test function names. A criterion's score is the
share of its checks that pass, so **a score can only move when an artifact
moves.**

Every check carries the remediation that would make it pass and the files that
change should touch, which is what turns a failing check into a task.

The initial backlog — a Korean persona, adversarial red-team cases, and fixed
behavioural scenarios — is implemented. The next handoff deliberately raises
the bar with Korean safety-policy coverage, because identity examples without
translated refusal and escalation rules would leave Korean users with weaker
safeguards. The safety policy is now implemented and its check also verifies
substantive refusal, self-harm, and emergency language; the next handoff is
Korean privacy-policy coverage.

> Earlier versions of this loop scored differently: a criterion improved
> whenever the previous iteration had merely *printed* a recommendation for it.
> Scores rose on their own, all eight reached target after ~50 runs, and the
> loop then regenerated an identical report 200 more times while nothing about
> Hanik was ever built. `reports/iteration-0001.html` through `-0250.html` are
> that history, kept as a record. See [`DECISIONS.md`](DECISIONS.md) §7.

## Running locally

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
python3 -m src.hanik_loop
```

One invocation performs exactly one iteration. It writes:

| Artifact | Purpose |
| --- | --- |
| `reports/iteration-NNNN.html` | Human-readable evidence and open tasks |
| `reports/iteration-NNNN.json` | Machine-readable companion |
| `reports/index.html` | Every iteration, newest first |
| `state/state.json` | Iteration counter, recent history, stagnation counter |
| `state/archive/` | Older history, pruned but never lost |
| `state/next-session.md` | The brief for the next session |

## Continuous mode

The workflow runs one implementation/evaluation iteration per invocation and
then asks for the next one, so each iteration is an independent session on a
clean runner. Copilot CLI reads `state/next-session.md`, changes the repository,
and is required to leave a non-empty diff before evaluation. Continuation is
earned, not automatic: the loop sets `should_continue` when the run succeeds,
the evidence changed recently (or a clean score needs a new check), and
continuation was not disabled.

Requirements for the chain to continue:

- `HANIK_KILL_SWITCH` is not `true` (checked before checkout).
- `HANIK_CONTINUOUS` is not `false`.
- The repository secret `HANIK_DISPATCH_TOKEN` exists — a minimally-scoped
  token dedicated to this one purpose (see [`SECURITY.md`](SECURITY.md)).

| Variable | Default | Meaning |
| --- | --- | --- |
| `HANIK_KILL_SWITCH` | unset | `true` stops the workflow before it does anything |
| `HANIK_CONTINUOUS` | `true` | `false` stops the chain after the current run |
| `HANIK_STAGNATION_LIMIT` | `2` | Consecutive no-change iterations before stopping |
| `HANIK_HISTORY_LIMIT` | `50` | History entries kept in `state/state.json` |
| `HANIK_MAX_ITERATIONS` | `10000` | Absolute ceiling on the iteration counter |

A failed run never chains. Neither does a stagnant one: if the evidence has not
changed for `HANIK_STAGNATION_LIMIT` iterations, re-running cannot help, so the
workflow stops and says why in the job summary.

This is deliberately different from running the evaluator repeatedly. A fresh
runner alone cannot improve Hanik; the implementation session is the part that
turns the previous brief into a real artifact change. If Copilot makes no
change, the workflow fails before it can create a false-progress report.

## The loop cannot finish

All checks passing means the bar is too low, not that Hanik is done. In that
state the report and the brief both say the same thing: add a check for a
capability Hanik genuinely lacks, and let the next iteration fail it.

## Repository map

| Path | Purpose |
| --- | --- |
| `hanik/persona.md` | Identity, voice, limitations, escalation |
| `hanik/persona.ko.md` | Korean identity, boundaries, examples, and handoff |
| `hanik/policies/` | Safety and privacy policies |
| `hanik/benchmarks/` | Behavioural regression scenarios |
| `src/checks.py` | Evidence checks; failing ones are the backlog |
| `src/hanik_loop.py` | Orchestration, scoring, stagnation detection |
| `src/reporting.py` | Report, JSON companion, index, session brief |
| `src/state.py` | Atomic writes, pruning, lossless archive |
| `AGENTS.md` | What every session must do |
| `HANIK_SPEC.md` | Requirements vs. hypotheses, per criterion |
| `SECURITY.md` | Threat model and emergency shutdown |
| `DECISIONS.md` | Why it is built this way, and what was rejected |
