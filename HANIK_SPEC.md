# Hanik Virtual-Human Specification

This document defines the identity, behavioral, and evaluation requirements
for the "Hanik" virtual human, and the criteria used by the automated
improvement loop (`src/hanik_loop.py`) to evaluate each iteration.

Every clause is explicitly labeled **Requirement** (must hold today, is
tested or enforced by tooling) or **Hypothesis** (a design idea, aspiration,
or future direction that is not yet enforced and may change). This
distinction exists so that no one — human reviewer or automated agent —
mistakes an untested idea for a guaranteed property of the system.

## 1. Identity

- **Requirement:** Hanik must always identify itself as a non-human,
  AI-based assistant. It must never claim to be a human, a licensed
  professional (e.g. doctor, lawyer), or a specific real person.
- **Requirement:** Generated artifacts (reports, commit messages, PR
  descriptions) must clearly state they were produced by an automated loop,
  including the iteration number and timestamp.
- **Hypothesis:** A persistent "persona" (name, tone, avatar) may be layered
  on top of the assistant identity in the future, but it must never obscure
  the underlying AI disclosure above.

## 2. Transparency

- **Requirement:** Every iteration produces a human-readable HTML report
  under `reports/` that records: the criteria evaluated, the score assigned
  to each, and the recommendations generated for the next iteration.
- **Requirement:** All report content derived from state or external input
  is HTML-escaped before rendering, so the report cannot be used to smuggle
  hidden markup, scripts, or misleading formatting.
- **Requirement:** Known limitations of the loop (see `DECISIONS.md`) are
  documented rather than silently hidden.
- **Hypothesis:** Future iterations may add machine-readable (JSON/JSON-LD)
  companions to the HTML report for programmatic consumption.

## 3. Human Control

- **Requirement:** The improvement loop only runs when explicitly triggered
  by a human (`workflow_dispatch`) or by a bounded, opt-in automated
  dispatch chain (`repository_dispatch`) that requires
  `HANIK_CONTINUOUS=true` to be set. It is never scheduled to run
  indefinitely by default.
- **Requirement:** A human can stop the loop at any time by not re-running
  the workflow, revoking the dispatch token, or setting
  `HANIK_CONTINUOUS=false`.
- **Requirement:** Every generated change (reports, state) is delivered via
  a pull request, subject to normal human review and merge gating, not
  pushed directly to the default branch by an unattended process.
- **Hypothesis:** A future "kill switch" repository variable could be
  checked at the very start of the workflow to short-circuit execution
  even before checkout, for defense in depth.

## 4. Safety

- **Requirement:** The loop never executes recommendations automatically;
  recommendations are descriptive text for a human to act on, not commands
  that are run.
- **Requirement:** The loop performs no network calls and depends on no
  external LLM or third-party API, eliminating an entire class of prompt
  injection, data exfiltration, and unpredictable-output risks.
- **Requirement:** All scores are bounded (`BASE_SCORE` .. `MAX_SCORE`) and
  iteration count is bounded (`HANIK_MAX_ITERATIONS`), so the system cannot
  claim unbounded "improvement" or run unbounded compute.
- **Hypothesis:** If a future iteration integrates a real LLM, it must first
  add prompt-injection defenses described in `SECURITY.md` before that
  capability is enabled by default.

## 5. Privacy

- **Requirement:** The loop must not collect, request, or store personal
  data about any individual. State and reports contain only criteria
  names, scores, recommendation text, and timestamps.
- **Requirement:** No secrets, tokens, or credentials are ever written to
  `state/state.json` or `reports/*.html`.
- **Hypothesis:** If user-submitted content is ever incorporated into the
  loop, it must be reviewed for PII and redacted before being persisted.

## 6. Memory

- **Requirement:** State is persisted in `state/state.json` and updated
  atomically (temp file + `os.replace`), so a crash or concurrent write can
  never leave state truncated or corrupted.
- **Requirement:** If `state/state.json` is missing or corrupted, the loop
  recovers automatically to a fresh, valid empty state rather than
  crashing or silently propagating bad data.
- **Requirement:** Each iteration's full evaluation (scores, recommendations,
  report path, timestamp) is appended to `history` so later iterations, and
  human reviewers, can audit the trajectory of the loop over time.
- **Hypothesis:** History may be pruned or archived after a large number of
  iterations to keep `state/state.json` from growing unbounded; this is not
  yet implemented.

## 7. Evaluation Criteria

The loop evaluates each iteration against eight explicit criteria,
mirroring the sections above: `identity`, `transparency`, `human_control`,
`safety`, `privacy`, `memory`, `evaluation`, and `oversight`. Each criterion
is scored between `0.0` and `0.95` (see `DECISIONS.md` for why `1.0` is
deliberately unreachable), and any criterion below the target score of
`0.9` generates a concrete recommendation for the next iteration.

- **Requirement:** Every iteration must critically re-evaluate the previous
  iteration's scores and recommendations rather than treating them as
  already resolved; scores only improve for criteria that had an open
  recommendation last time (see `evaluate_previous_iteration` in
  `src/hanik_loop.py`).
- **Hypothesis:** Additional criteria (e.g. accessibility, localization)
  may be added in future iterations; adding a criterion should never
  silently invalidate historical scores for existing criteria.

## 8. Oversight

- **Requirement:** All loop output is delivered as a pull request. No
  automated process merges its own pull request.
- **Requirement:** The GitHub Actions workflow requests least-privilege
  permissions (`contents: write`, `pull-requests: write` only where
  needed) and never grants itself administrative or org-wide scopes.
- **Requirement:** A failed run does not trigger the next iteration's
  dispatch; only a successful run may optionally chain forward, and only
  when `HANIK_CONTINUOUS=true` is explicitly set.
- **Hypothesis:** A future iteration may add a required human "approve to
  continue" step between iterations, rather than relying solely on the
  `HANIK_CONTINUOUS` flag and PR review.
