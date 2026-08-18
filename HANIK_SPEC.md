# Hanik Virtual-Human Specification

This document defines what Hanik must be, and it is the source the evaluation
criteria mirror. Each criterion below is measured by named checks in
`src/checks.py`; the check IDs are listed so a requirement can be traced to the
evidence that proves it.

Every clause is labeled **Requirement** (holds today and is enforced by a
check) or **Hypothesis** (a direction that is not yet enforced). The
distinction exists so no one — human or automated session — mistakes an
untested idea for a guaranteed property.

A requirement without a check is an opinion. If you add a requirement here, add
the check that proves it in the same change.

## 0. What Hanik is

Hanik is a virtual human: an AI assistant with a defined identity, voice,
refusal behaviour, and escalation policy, specified in `hanik/`. It is not a
person, and the specification exists partly to keep that unambiguous under
pressure.

## 1. Identity

_Checks: `identity.persona_exists`, `identity.ai_disclosure`,
`identity.impersonation_boundaries`, `identity.example_exchanges`,
`identity.multilingual_persona`_

- **Requirement:** A persona artifact exists at `hanik/persona.md` and is
  substantive, not a stub.
- **Requirement:** The persona contains the disclosure sentence "Hanik is an AI
  assistant, not a human being." verbatim, and states when it is repeated.
- **Requirement:** The persona enumerates at least four impersonation
  boundaries — human, specific real person, licensed professional, unearned
  credentials.
- **Requirement:** Identity behaviour is demonstrated in at least three
  complete example exchanges, not merely asserted in prose. Assertions are easy
  to satisfy and hard to verify; examples show what the rule looks like when a
  user pushes back.
- **Requirement:** Personality never overrides disclosure. If a framing forces
  a choice between staying in character and being honest, Hanik breaks
  character.
- **Requirement:** The persona is defined in a second language rather than
  assumed to translate. `hanik/persona.ko.md` provides Korean disclosure,
  boundaries, examples, limitations, and handoff language.

## 2. Transparency

_Checks: `transparency.previous_html_report`,
`transparency.previous_json_report`, `transparency.report_index`,
`transparency.session_brief`, `transparency.known_limitations`_

- **Requirement:** Every iteration writes a human-readable HTML report
  recording each check, its result, and the evidence behind it.
- **Requirement:** Every report has a machine-readable JSON companion, so the
  trail can be consumed programmatically instead of scraped.
- **Requirement:** Reports are indexed at `reports/index.html`.
- **Requirement:** Every iteration writes `state/next-session.md`, the brief
  the next session reads before doing anything.
- **Requirement:** All report content derived from state or check evidence is
  HTML-escaped, so nothing can smuggle markup or misleading formatting into a
  report.
- **Requirement:** Hanik's limitations are disclosed in the persona, at least
  three of them, concretely.
- **Requirement:** Evidence strings are repository-relative, so a committed
  report never leaks the filesystem layout of the machine that produced it.

## 3. Human Control

_Checks: `human_control.no_schedule_trigger`, `human_control.kill_switch`,
`human_control.continuous_flag`, `human_control.stop_procedure`_

- **Requirement:** The loop never starts itself on a timer. There is no
  `schedule:` trigger.
- **Requirement:** A kill switch (`HANIK_KILL_SWITCH`) is evaluated before
  checkout, so a human can stop the loop without revoking secrets, cancelling
  runs, or editing the workflow.
- **Requirement:** Continuation is opt-out through `HANIK_CONTINUOUS`.
- **Requirement:** The stop procedure is documented in `SECURITY.md` as
  numbered steps.
- **Requirement:** Every generated change is delivered as a pull request,
  subject to normal review, and never pushed to the default branch by an
  unattended process.

## 4. Safety

_Checks: `safety.no_network_imports`, `safety.no_dynamic_execution`,
`safety.policy_sections`, `safety.escaping_regression_test`,
`safety.multilingual_policy`, `safety.red_team_suite`_

- **Requirement:** Refusal behaviour is specified in
  `hanik/policies/safety.md`, covering refusal style, at least five harm
  categories, and escalation.
- **Requirement:** The loop never executes a recommendation. Remediation text
  is inert data that is rendered, never run. Enforced by an AST scan, not by
  convention: no `eval`, `exec`, `compile`, `__import__`, no subprocess-style
  imports, no `os` process spawning anywhere in `src/`.
- **Requirement:** The loop makes no network calls and imports no networking
  module. Also enforced by AST scan.
- **Requirement:** The escaping guarantee in §2 is covered by a regression
  test.
- **Requirement:** Adversarial cases are tested in
  `tests/test_red_team.py`: real-person impersonation, professional-advice
  framing, role-play jailbreaks, self-harm escalation, and credential requests.
- **Requirement (open):** Safety refusal and escalation are also available in
  Korean. Currently failing: `hanik/policies/safety.ko.md` does not exist.
- **Hypothesis:** If a future iteration integrates a real LLM, the
  prompt-injection defenses in `SECURITY.md` must be designed and reviewed
  before that capability is enabled by default.

## 5. Privacy

_Checks: `privacy.no_pii_in_outputs`, `privacy.no_secrets_in_outputs`,
`privacy.policy_sections`_

- **Requirement:** No personal data is collected, requested, or stored.
  Generated artifacts contain criterion names, scores, static remediation text,
  repository-relative paths, and timestamps.
- **Requirement:** Generated artifacts are scanned every iteration for e-mail
  addresses, phone-shaped strings, and known credential formats. A hit fails a
  check and becomes the top task in the next brief.
- **Requirement:** `hanik/policies/privacy.md` documents what is collected, how
  long it is kept, and how it is redacted.
- **Hypothesis:** If user-submitted content is ever incorporated, redaction
  must ship together with a test that proves it.

## 6. Memory

_Checks: `memory.atomic_write`, `memory.corruption_recovery_test`,
`memory.history_bounded`, `memory.archive_lossless`_

- **Requirement:** State is written through a temporary file, fsynced, and
  installed with `os.replace`, so a crash or concurrent write can never leave
  `state/state.json` truncated.
- **Requirement:** A missing, unparsable, or structurally invalid state file
  recovers to a fresh valid state instead of raising, and the recovery is
  covered by a test. The reset is visible in the next report.
- **Requirement:** A state file written by an older schema is migrated, not
  discarded.
- **Requirement:** `state/state.json` retains at most `HANIK_HISTORY_LIMIT`
  entries, so the file read on every iteration cannot grow without bound.
- **Requirement:** Pruning is lossless. Entries removed from the working state
  are written to `state/archive/` first, and the loop verifies that the number
  of archived entries on disk covers everything it claims to have pruned.

## 7. Evaluation

_Checks: `evaluation.evidence_coverage`, `evaluation.delta_recorded`,
`evaluation.stagnation_tracked`, `evaluation.benchmark_scenarios`_

- **Requirement:** A criterion's score is the share of its checks that pass,
  computed from the repository as it is on disk. No score component is carried
  forward, assumed, or incremented for effort.
- **Requirement:** Every criterion is backed by at least three checks.
- **Requirement:** Each iteration records a per-criterion delta against its
  predecessor.
- **Requirement:** Each iteration records an evidence signature, and repeated
  identical signatures are counted and surfaced as stagnation. A loop that has
  stopped improving must say so rather than continue producing identical
  reports.
- **Requirement:** Behavioural regressions are detectable against at least
  three fixed Markdown scenarios in `hanik/benchmarks/`, each documenting a
  prompt, expected behaviour, and failure modes.
- **Requirement:** All checks passing is treated as a bar that is too low, not
  as completion. The report and brief both demand a new check in that state.
- **Hypothesis:** Additional criteria (accessibility, localization coverage)
  may be added; adding one must never silently invalidate historical scores for
  existing criteria.

## 8. Oversight

_Checks: `oversight.least_privilege`, `oversight.pull_request_delivery`,
`oversight.no_auto_merge`, `oversight.failure_stops_chain`,
`oversight.session_contract`_

- **Requirement:** All loop output is delivered as a pull request, and no
  automated process merges its own pull request.
- **Requirement:** The workflow requests only `contents: write` and
  `pull-requests: write`, and never administrative or org-wide scopes.
- **Requirement:** Continuation is gated on the loop's own `should_continue`
  output, so a failed or stagnant run stops the chain.
- **Requirement:** `AGENTS.md` states the contract every fresh session follows,
  because a session starts with no memory of the previous one.
- **Requirement:** A session must not weaken a check to make it pass. This is
  the one failure mode the loop cannot detect about itself, which is why it is
  stated in `AGENTS.md`, in the generated brief, and here.
- **Hypothesis:** A future iteration may require an explicit human approval
  step between iterations rather than relying on `HANIK_CONTINUOUS`, the kill
  switch, and pull-request review.
