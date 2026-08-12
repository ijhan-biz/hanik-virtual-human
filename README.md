# hanik-virtual-human

An automated, self-critiquing improvement loop for the "Hanik" virtual
human project. Each iteration reads the prior state, critically evaluates
it against explicit criteria, generates recommendations for the next
iteration, writes a complete HTML report, and atomically updates the
persisted state -- entirely offline, with no external LLM or provider
credentials required.

## What this is

- **`src/hanik_loop.py`** -- the core loop. Provider-neutral and
  offline-capable: it makes no network calls and requires no API keys.
  See the module docstring for the full design rationale.
- **`tests/test_hanik_loop.py`** -- unit tests covering a full loop run,
  HTML escaping of untrusted content, corrupted-state recovery, atomic
  state writes, and the maximum-iteration guard.
- **`.github/workflows/hanik-loop.yml`** -- a GitHub Actions workflow that
  runs the loop's tests, executes one iteration, and (only when
  explicitly configured) opens/continues a pull request with the
  generated report and state. See [Continuous mode](#continuous-mode)
  below.
- **`HANIK_SPEC.md`** -- the specification for what Hanik must do
  (identity, transparency, human control, safety, privacy, memory,
  evaluation criteria, oversight), explicitly distinguishing hard
  requirements from open hypotheses.
- **`SECURITY.md`** -- the threat model: prompt/data injection, secrets
  handling, untrusted MCP servers, least privilege, cost/rate controls,
  retention, and emergency shutdown.
- **`DECISIONS.md`** -- why the loop is designed the way it is, and what
  alternatives were rejected and why.

## Running locally

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
python3 -m src.hanik_loop
```

Running `python3 -m src.hanik_loop` performs exactly one iteration: it
reads `state/state.json` (creating a fresh state if missing or
corrupted), writes `reports/iteration-NNNN.html`, and atomically updates
`state/state.json`.

## Continuous mode

By default, the workflow runs one iteration when manually triggered
(`workflow_dispatch`) and successful runs automatically request the next
iteration via `repository_dispatch` until the configured maximum is reached.
The following are required:

- `HANIK_CONTINUOUS` is not set to `false` (set it to `false` to stop
  continuation).
- The repository secret `HANIK_DISPATCH_TOKEN` exists and is a
  minimally-scoped token dedicated to this purpose (see `SECURITY.md`).
- `HANIK_MAX_ITERATIONS` has not yet been reached.

A failed run never triggers the next iteration. See `SECURITY.md` for the
full emergency-shutdown procedure and why a separate dispatch token (rather
than the default `GITHUB_TOKEN`) is used intentionally.

## Criteria at a glance

The loop evaluates every iteration against eight criteria defined in
`HANIK_SPEC.md`: `identity`, `transparency`, `human_control`, `safety`,
`privacy`, `memory`, `evaluation`, and `oversight`. Each criterion is
scored between `0.0` and `0.95` (see `DECISIONS.md` for why a "perfect"
score is deliberately unreachable), and any criterion below the target
score generates a recommendation captured in that iteration's report and
state history.
