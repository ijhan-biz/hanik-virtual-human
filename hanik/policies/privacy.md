# Hanik privacy policy

This policy governs what Hanik and its improvement loop may collect, keep, and
write down. It is measured by the `privacy.*` checks in `src/checks.py`.

## Data collected

- The improvement loop collects nothing about any person. Its inputs are files
  already in this repository: `hanik/`, `src/`, `tests/`,
  `.github/workflows/`, `state/state.json`, and `reports/`.
- Hanik itself treats conversation content as transient. It does not persist
  user messages into `state/state.json` or `reports/`, and there is no code
  path in this repository that would do so.
- No credentials, tokens, or environment variable values are ever written to
  generated artifacts. Generated artifacts contain criterion names, numeric
  scores, static remediation text, file paths, and timestamps.

## Retention

- `reports/` retains one HTML report and one JSON companion per iteration,
  permanently, as an auditable record.
- `state/state.json` retains only the most recent `HANIK_HISTORY_LIMIT`
  iterations (default 50). Older entries are moved to `state/archive/` rather
  than deleted, so the record stays complete while the working state file
  stays small.
- Because no personal data is collected, there is no personal-data retention
  window to enforce and no deletion request path to implement.

## Redaction

- Generated outputs are scanned every iteration for e-mail addresses,
  phone-number-shaped strings, and known credential formats. A match fails the
  `privacy.no_pii_in_outputs` or `privacy.no_secrets_in_outputs` check and
  becomes the top task in the next session brief.
- If user-submitted content is ever incorporated into the loop, it must be
  redacted before being persisted, and the redaction must be covered by a test
  before the capability ships.
- Report content derived from state is HTML-escaped, so an injected string can
  change neither the rendering nor the meaning of a report.
