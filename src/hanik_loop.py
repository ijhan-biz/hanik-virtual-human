"""Hanik virtual-human improvement loop.

This module implements a single, self-contained iteration of the "Hanik"
virtual-human improvement loop described in ``HANIK_SPEC.md``.

Design goals (see ``SECURITY.md`` and ``DECISIONS.md`` for rationale):

* **Provider-neutral / offline-capable** -- the loop never calls an external
  LLM or network service. All evaluation is rule-based and deterministic so
  the loop can run entirely inside a sandboxed CI runner with no secrets or
  outbound network access required.
* **Secure by construction** -- all text that originates from state (which is
  repository-controlled but still treated as untrusted input) is HTML
  escaped before being written into the generated report. State updates are
  written atomically (temp file + ``os.replace``) so a crash or concurrent
  run can never leave ``state/state.json`` truncated or corrupted.
* **Bounded** -- the loop enforces a maximum iteration count so that it can
  never run forever, and it raises a dedicated exception when the bound is
  reached so callers (including the GitHub Actions workflow) can stop
  cleanly instead of silently looping.
"""

from __future__ import annotations

import copy
import html
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The explicit Hanik evaluation criteria. Order is significant only for
#: display purposes; each criterion is evaluated independently.
HANIK_CRITERIA: List[str] = [
    "identity",
    "transparency",
    "human_control",
    "safety",
    "privacy",
    "memory",
    "evaluation",
    "oversight",
]

#: Human-readable descriptions used in reports and recommendations.
CRITERIA_DESCRIPTIONS: Dict[str, str] = {
    "identity": "Hanik consistently represents itself as a non-human AI assistant.",
    "transparency": "Hanik's capabilities, limitations, and data sources are disclosed.",
    "human_control": "A human can pause, override, or shut down the loop at any time.",
    "safety": "Outputs avoid harmful, deceptive, or unsafe recommendations.",
    "privacy": "No personal or sensitive data is collected, stored, or leaked.",
    "memory": "State is durable, auditable, and recoverable from corruption.",
    "evaluation": "Each iteration is critically assessed against prior iterations.",
    "oversight": "Humans retain the ability to review and reject recommendations.",
}

#: Suggested improvements offered when a criterion has not yet reached the
#: target score. These are illustrative, non-executable recommendations --
#: the loop never automatically applies them.
CRITERIA_RECOMMENDATIONS: Dict[str, str] = {
    "identity": "Add an explicit self-identification statement to user-facing output.",
    "transparency": "Document data sources and known limitations in HANIK_SPEC.md.",
    "human_control": "Verify the workflow_dispatch manual stop path is documented and tested.",
    "safety": "Add a regression test for a previously identified unsafe recommendation.",
    "privacy": "Audit state/state.json and reports/ for accidental PII before each release.",
    "memory": "Add a corrupted-state recovery test if one does not already exist.",
    "evaluation": "Compare this iteration's scores against the prior iteration explicitly.",
    "oversight": "Require a human-reviewed pull request before merging generated changes.",
}

#: Baseline score assigned to a criterion that has never been evaluated.
BASE_SCORE = 0.4
#: Score increment applied when a criterion received a recommendation in the
#: previous iteration (i.e. it is assumed to have been worked on).
IMPROVEMENT_STEP = 0.1
#: Criteria never automatically reach a "perfect" score -- there is always
#: room for renewed critical evaluation.
MAX_SCORE = 0.95
#: A criterion at or above this score is considered satisfied for the
#: current iteration and will not generate a new recommendation.
TARGET_SCORE = 0.9

DEFAULT_STATE_PATH = Path("state/state.json")
DEFAULT_REPORTS_DIR = Path("reports")

#: Environment variable that must be explicitly set to enable indefinite
#: repeated execution (see .github/workflows/hanik-loop.yml).
CONTINUOUS_ENV_VAR = "HANIK_CONTINUOUS"
#: Environment variable bounding the total number of iterations ever
#: allowed to run. Must be a positive integer.
MAX_ITERATIONS_ENV_VAR = "HANIK_MAX_ITERATIONS"
#: Fallback maximum iteration count used when the environment variable is
#: absent or invalid, so the loop is always bounded by default.
DEFAULT_MAX_ITERATIONS = 50


class HanikLoopError(Exception):
    """Base class for all Hanik loop errors."""


class MaxIterationsReachedError(HanikLoopError):
    """Raised when running another iteration would exceed the configured
    maximum iteration count."""

    def __init__(self, iteration: int, max_iterations: int) -> None:
        super().__init__(
            f"Refusing to run iteration {iteration}: "
            f"maximum of {max_iterations} iterations reached."
        )
        self.iteration = iteration
        self.max_iterations = max_iterations


@dataclass
class IterationResult:
    """The outcome of running a single loop iteration."""

    iteration: int
    timestamp: str
    scores: Dict[str, float]
    recommendations: List[Dict[str, str]]
    report_path: Path
    state_path: Path
    state: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# State handling
# ---------------------------------------------------------------------------


def _empty_state() -> Dict[str, Any]:
    return {"iteration": 0, "history": []}


def load_state(state_path: Path = DEFAULT_STATE_PATH) -> Dict[str, Any]:
    """Load prior state from ``state_path``.

    If the file does not exist, a fresh empty state is returned. If the file
    exists but contains invalid JSON or an unexpected structure (corrupted
    state), the error is swallowed and a fresh empty state is returned so the
    loop can always make forward progress instead of crashing.
    """

    if not state_path.exists():
        return _empty_state()

    try:
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return _empty_state()

    if not isinstance(data, dict):
        return _empty_state()

    iteration = data.get("iteration")
    history = data.get("history")
    if not isinstance(iteration, int) or iteration < 0:
        return _empty_state()
    if not isinstance(history, list):
        return _empty_state()

    return {"iteration": iteration, "history": history}


def save_state_atomic(state: Dict[str, Any], state_path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomically write ``state`` as JSON to ``state_path``.

    Writes to a temporary file in the same directory and then uses
    ``os.replace`` (an atomic rename on POSIX and Windows) so a reader can
    never observe a partially-written or truncated state file, even if the
    process crashes mid-write or two writers race.
    """

    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".state-", suffix=".tmp", dir=str(state_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(state, tmp_file, indent=2, ensure_ascii=True, sort_keys=True)
            tmp_file.write("\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, state_path)
    finally:
        # If os.replace succeeded the temp file no longer exists at
        # tmp_name; if an error occurred before that, clean up the leftover.
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _previous_entry(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    history = state.get("history") or []
    if not history:
        return None
    return history[-1]


def evaluate_previous_iteration(state: Dict[str, Any]) -> Dict[str, float]:
    """Critically evaluate the previous iteration and compute new scores.

    Every criterion that received a recommendation in the previous
    iteration is assumed to have been acted upon and its score improves by
    ``IMPROVEMENT_STEP``, capped at ``MAX_SCORE``. Criteria without a prior
    recommendation (already at or above target) keep their previous score.
    Criteria with no history at all start from ``BASE_SCORE``.
    """

    previous = _previous_entry(state)
    previous_scores: Dict[str, float] = {}
    previous_recommended: set = set()

    if previous:
        raw_scores = previous.get("scores") or {}
        if isinstance(raw_scores, dict):
            previous_scores = {
                k: float(v) for k, v in raw_scores.items() if k in HANIK_CRITERIA
            }
        raw_recs = previous.get("recommendations") or []
        if isinstance(raw_recs, list):
            previous_recommended = {
                rec.get("criterion")
                for rec in raw_recs
                if isinstance(rec, dict) and rec.get("criterion") in HANIK_CRITERIA
            }

    new_scores: Dict[str, float] = {}
    for criterion in HANIK_CRITERIA:
        base = previous_scores.get(criterion, BASE_SCORE)
        if criterion in previous_recommended:
            base = min(MAX_SCORE, base + IMPROVEMENT_STEP)
        new_scores[criterion] = round(base, 4)

    return new_scores


def generate_recommendations(scores: Dict[str, float]) -> List[Dict[str, str]]:
    """Generate next-step recommendations for criteria below target score."""

    recommendations = []
    for criterion in HANIK_CRITERIA:
        score = scores.get(criterion, BASE_SCORE)
        if score < TARGET_SCORE:
            recommendations.append(
                {
                    "criterion": criterion,
                    "score": score,
                    "recommendation": CRITERIA_RECOMMENDATIONS[criterion],
                }
            )
    return recommendations


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_html_report(
    iteration: int,
    timestamp: str,
    scores: Dict[str, float],
    recommendations: List[Dict[str, str]],
    previous_entry: Optional[Dict[str, Any]] = None,
) -> str:
    """Render a complete, self-contained HTML report.

    All dynamic text -- including free-form text carried over from
    ``previous_entry`` (which originates from the state file and must be
    treated as untrusted) -- is passed through :func:`html.escape` before
    being embedded in the document to prevent HTML/script injection.
    """

    esc = html.escape

    rows = []
    for criterion in HANIK_CRITERIA:
        score = scores.get(criterion, BASE_SCORE)
        description = esc(CRITERIA_DESCRIPTIONS[criterion])
        rows.append(
            "      <tr>"
            f"<td>{esc(criterion)}</td>"
            f"<td>{esc(f'{score:.2f}')}</td>"
            f"<td>{description}</td>"
            "</tr>"
        )
    rows_html = "\n".join(rows)

    if recommendations:
        rec_lines = []
        for rec in recommendations:
            score_str = "{:.2f}".format(rec["score"])
            rec_lines.append(
                "      <li>"
                f"<strong>{esc(rec['criterion'])}</strong> "
                f"(score {esc(score_str)}): "
                f"{esc(rec['recommendation'])}"
                "</li>"
            )
        rec_items = "\n".join(rec_lines)
        rec_html = f"    <ul>\n{rec_items}\n    </ul>"
    else:
        rec_html = "    <p>All criteria meet or exceed the target score.</p>"

    title = esc(f"Hanik Improvement Loop -- Iteration {iteration}")
    generated = esc(timestamp)

    # The previous iteration's recommendation text originates from the
    # state file (which may have been hand-edited or come from an
    # untrusted source) and is echoed here verbatim for audit purposes, so
    # it must be escaped just like any other dynamic content.
    if previous_entry:
        prev_recs = previous_entry.get("recommendations") or []
        prev_timestamp = esc(str(previous_entry.get("timestamp", "unknown")))
        if prev_recs:
            prev_lines = []
            for rec in prev_recs:
                if not isinstance(rec, dict):
                    continue
                criterion = esc(str(rec.get("criterion", "unknown")))
                text = esc(str(rec.get("recommendation", "")))
                prev_lines.append(f"      <li><strong>{criterion}</strong>: {text}</li>")
            prev_html = (
                f"    <p>From iteration recorded at {prev_timestamp}:</p>\n"
                f"    <ul>\n" + "\n".join(prev_lines) + "\n    </ul>"
            )
        else:
            prev_html = f"    <p>No open recommendations as of {prev_timestamp}.</p>"
    else:
        prev_html = "    <p>No previous iteration on record.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
</head>
<body>
  <h1>{title}</h1>
  <p>Generated at: {generated}</p>

  <h2>Critique of Previous Iteration</h2>
{prev_html}

  <h2>Criteria Scores</h2>
  <table border="1" cellpadding="4" cellspacing="0">
    <thead>
      <tr><th>Criterion</th><th>Score</th><th>Description</th></tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>

  <h2>Recommendations for Next Iteration</h2>
{rec_html}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Iteration bound
# ---------------------------------------------------------------------------


def get_max_iterations() -> int:
    """Return the configured maximum iteration count.

    Reads ``HANIK_MAX_ITERATIONS`` from the environment. Falls back to
    ``DEFAULT_MAX_ITERATIONS`` if unset, non-numeric, or not a positive
    integer, so the loop is always bounded.
    """

    raw = os.environ.get(MAX_ITERATIONS_ENV_VAR)
    if raw is None:
        return DEFAULT_MAX_ITERATIONS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ITERATIONS
    if value <= 0:
        return DEFAULT_MAX_ITERATIONS
    return value


# ---------------------------------------------------------------------------
# Loop entry point
# ---------------------------------------------------------------------------


def run_iteration(
    state_path: Path = DEFAULT_STATE_PATH,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    max_iterations: Optional[int] = None,
) -> IterationResult:
    """Run a single Hanik improvement-loop iteration.

    1. Load prior state (recovering from corruption if necessary).
    2. Enforce the maximum iteration guard.
    3. Critically evaluate the previous iteration against the Hanik
       criteria and compute new scores.
    4. Generate recommendations for the next iteration.
    5. Render and write an escaped HTML report under ``reports_dir``.
    6. Atomically persist the updated state under ``state_path``.
    """

    if max_iterations is None:
        max_iterations = get_max_iterations()

    state = load_state(state_path)
    next_iteration = state["iteration"] + 1

    if next_iteration > max_iterations:
        raise MaxIterationsReachedError(next_iteration, max_iterations)

    scores = evaluate_previous_iteration(state)
    recommendations = generate_recommendations(scores)
    timestamp = datetime.now(timezone.utc).isoformat()
    previous_entry = _previous_entry(state)

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"iteration-{next_iteration:04d}.html"
    report_html = render_html_report(
        next_iteration, timestamp, scores, recommendations, previous_entry
    )
    report_path.write_text(report_html, encoding="utf-8")

    new_state = copy.deepcopy(state)
    new_state["iteration"] = next_iteration
    new_state.setdefault("history", []).append(
        {
            "iteration": next_iteration,
            "timestamp": timestamp,
            "scores": scores,
            "recommendations": recommendations,
            "report_path": str(report_path.as_posix()),
        }
    )

    save_state_atomic(new_state, state_path)

    return IterationResult(
        iteration=next_iteration,
        timestamp=timestamp,
        scores=scores,
        recommendations=recommendations,
        report_path=report_path,
        state_path=state_path,
        state=new_state,
    )


def main() -> int:
    """CLI entry point used by the GitHub Actions workflow."""

    try:
        result = run_iteration()
    except MaxIterationsReachedError as exc:
        print(str(exc))
        return 1

    print(f"Hanik loop iteration {result.iteration} complete.")
    print(f"Report: {result.report_path}")
    print(f"State: {result.state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
