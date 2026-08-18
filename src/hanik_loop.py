"""Hanik virtual-human improvement loop.

One run of this module is one iteration, and one iteration is meant to be one
fresh session: the loop keeps no memory in process, reads everything it needs
from disk, and hands the next session a written brief.

An iteration does five things:

1. Load prior state, recovering automatically if it was corrupted.
2. Measure the virtual human against the evidence checks in :mod:`src.checks`,
   which read the actual artifacts under ``hanik/``, ``src/``, ``tests/`` and
   ``.github/workflows/``.
3. Score each criterion as the share of its checks that pass, and compare
   against the previous iteration.
4. Write the report, its machine-readable companion, the report index, and the
   brief for the next session.
5. Persist state atomically, pruning old history into ``state/archive/``.

What changed and why
--------------------

The original loop raised a criterion's score whenever the previous iteration
had emitted a recommendation for it, regardless of whether anything had been
done about it. Scores therefore climbed on their own, every criterion reached
the target after a fixed number of runs, and the loop then regenerated an
identical report forever -- 250 times, in this repository's history. It also
measured only itself: there was no virtual human in the repository to improve.

Now scores are a function of the repository's contents alone. Nothing improves
unless an artifact changes, an unchanged repository is reported as stagnant,
and the failing checks are handed to the next session as a concrete backlog.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import reporting
from .checks import (
    CHECKS,
    HANIK_CRITERIA,
    Check,
    CheckContext,
    CheckResult,
    evidence_signature,
    overall_score,
    run_checks,
    score_criteria,
)
from .state import (
    DEFAULT_STATE_PATH,
    get_history_limit,
    load_state,
    prune_history,
    save_state_atomic,
)

DEFAULT_REPORTS_DIR = Path("reports")

#: A finite ceiling on the iteration counter. It exists so the loop is
#: provably bounded, not as the day-to-day control -- stagnation detection is
#: what actually stops a chain that has nothing left to do.
DEFAULT_MAX_ITERATIONS = 10_000
MAX_ITERATIONS_ENV_VAR = "HANIK_MAX_ITERATIONS"

#: Consecutive iterations without any change in evidence before the loop stops
#: asking for another run. Re-running an unchanged repository cannot improve
#: it, so continuing would only burn CI minutes and open empty pull requests.
DEFAULT_STAGNATION_LIMIT = 2
STAGNATION_LIMIT_ENV_VAR = "HANIK_STAGNATION_LIMIT"

CONTINUOUS_ENV_VAR = "HANIK_CONTINUOUS"


class HanikLoopError(Exception):
    """Base class for all Hanik loop errors."""


class MaxIterationsReachedError(HanikLoopError):
    """Raised when running another iteration would exceed the configured bound."""

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
    deltas: Dict[str, float]
    overall: float
    results: List[CheckResult]
    open_tasks: List[CheckResult]
    progress: bool
    stagnant_iterations: int
    should_continue: bool
    report_path: Path
    json_report_path: Path
    index_path: Path
    brief_path: Path
    state_path: Path
    state: Dict[str, Any] = field(default_factory=dict)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def get_max_iterations() -> int:
    """Return the absolute iteration ceiling, always a positive integer."""

    return _positive_int_env(MAX_ITERATIONS_ENV_VAR, DEFAULT_MAX_ITERATIONS)


def get_stagnation_limit() -> int:
    """Return how many no-progress iterations are tolerated before stopping."""

    return _positive_int_env(STAGNATION_LIMIT_ENV_VAR, DEFAULT_STAGNATION_LIMIT)


def continuation_enabled() -> bool:
    """Return False when a human has explicitly disabled continuation."""

    return os.environ.get(CONTINUOUS_ENV_VAR, "").strip().lower() != "false"


def _previous_entry(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    history = state.get("history") or []
    return history[-1] if history else None


def compute_deltas(
    scores: Dict[str, float], previous_entry: Optional[Dict[str, Any]]
) -> Dict[str, float]:
    """Return this iteration's score change per criterion.

    Absent history counts as a zero baseline, so the first iteration reports
    exactly what it earned rather than an undefined delta.
    """

    previous_scores: Dict[str, float] = {}
    if previous_entry:
        raw = previous_entry.get("scores")
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in HANIK_CRITERIA and isinstance(value, (int, float)):
                    previous_scores[key] = float(value)

    return {
        criterion: round(scores.get(criterion, 0.0) - previous_scores.get(criterion, 0.0), 4)
        for criterion in HANIK_CRITERIA
    }


def run_iteration(
    state_path: Path = DEFAULT_STATE_PATH,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    repo_root: Optional[Path] = None,
    max_iterations: Optional[int] = None,
    history_limit: Optional[int] = None,
    stagnation_limit: Optional[int] = None,
    checks: Optional[Sequence[Check]] = None,
) -> IterationResult:
    """Run one Hanik improvement-loop iteration."""

    if max_iterations is None:
        max_iterations = get_max_iterations()
    if history_limit is None:
        history_limit = get_history_limit()
    if stagnation_limit is None:
        stagnation_limit = get_stagnation_limit()
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    if checks is None:
        checks = CHECKS

    state = load_state(state_path)
    next_iteration = state["iteration"] + 1
    if next_iteration > max_iterations:
        raise MaxIterationsReachedError(next_iteration, max_iterations)

    context = CheckContext(
        repo_root=Path(repo_root),
        state=state,
        state_path=state_path,
        reports_dir=reports_dir,
        history_limit=history_limit,
    )
    results = run_checks(context, checks)
    scores = score_criteria(results)
    overall = overall_score(scores)
    open_tasks = [result for result in results if not result.passed]

    previous_entry = _previous_entry(state)
    deltas = compute_deltas(scores, previous_entry)
    signature = evidence_signature(results)

    previous_signature = previous_entry.get("signature") if previous_entry else None
    progress = previous_signature != signature
    stagnant_iterations = 0 if progress else int(state.get("stagnant_iterations") or 0) + 1

    timestamp = datetime.now(timezone.utc).isoformat()

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"iteration-{next_iteration:04d}.html"
    json_report_path = reports_dir / f"iteration-{next_iteration:04d}.json"
    index_path = reports_dir / "index.html"
    brief_path = state_path.parent / "next-session.md"

    report_path.write_text(
        reporting.render_html_report(
            iteration=next_iteration,
            timestamp=timestamp,
            scores=scores,
            deltas=deltas,
            overall=overall,
            results=results,
            open_tasks=open_tasks,
            stagnant_iterations=stagnant_iterations,
            progress=progress,
        ),
        encoding="utf-8",
    )
    json_report_path.write_text(
        json.dumps(
            reporting.render_json_report(
                iteration=next_iteration,
                timestamp=timestamp,
                scores=scores,
                deltas=deltas,
                overall=overall,
                results=results,
                stagnant_iterations=stagnant_iterations,
                progress=progress,
            ),
            indent=2,
            ensure_ascii=True,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    index_path.write_text(reporting.render_index_html(reports_dir), encoding="utf-8")

    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        reporting.render_session_brief(
            iteration=next_iteration,
            timestamp=timestamp,
            scores=scores,
            overall=overall,
            results=results,
            open_tasks=open_tasks,
            stagnant_iterations=stagnant_iterations,
            progress=progress,
        ),
        encoding="utf-8",
    )

    new_state = dict(state)
    new_state["iteration"] = next_iteration
    new_state["stagnant_iterations"] = stagnant_iterations
    new_state["history"] = list(state.get("history") or [])
    new_state["history"].append(
        {
            "iteration": next_iteration,
            "timestamp": timestamp,
            "scores": scores,
            "deltas": deltas,
            "overall_score": overall,
            "signature": signature,
            "progress": progress,
            "open_tasks": [task.id for task in open_tasks],
            "report_path": report_path.as_posix(),
            "json_report_path": json_report_path.as_posix(),
        }
    )
    prune_history(new_state, state_path, history_limit)
    save_state_atomic(new_state, state_path)

    should_continue = (
        continuation_enabled()
        and bool(open_tasks)
        and stagnant_iterations < stagnation_limit
        and next_iteration < max_iterations
    )

    return IterationResult(
        iteration=next_iteration,
        timestamp=timestamp,
        scores=scores,
        deltas=deltas,
        overall=overall,
        results=results,
        open_tasks=open_tasks,
        progress=progress,
        stagnant_iterations=stagnant_iterations,
        should_continue=should_continue,
        report_path=report_path,
        json_report_path=json_report_path,
        index_path=index_path,
        brief_path=brief_path,
        state_path=state_path,
        state=new_state,
    )


def workflow_outputs(result: IterationResult) -> Dict[str, str]:
    """Return the key/value pairs the GitHub Actions workflow consumes."""

    return {
        "status": "success",
        "iteration": str(result.iteration),
        "overall_score": f"{result.overall:.4f}",
        "checks_passed": str(sum(1 for check in result.results if check.passed)),
        "checks_total": str(len(result.results)),
        "open_tasks": str(len(result.open_tasks)),
        "progress": "true" if result.progress else "false",
        "stagnant_iterations": str(result.stagnant_iterations),
        "should_continue": "true" if result.should_continue else "false",
    }


def write_github_output(outputs: Dict[str, str], path: Optional[str] = None) -> bool:
    """Append ``outputs`` to the GitHub Actions output file, if running there."""

    target = path or os.environ.get("GITHUB_OUTPUT")
    if not target:
        return False
    with open(target, "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")
    return True


def _summarise(result: IterationResult) -> str:
    passed = sum(1 for check in result.results if check.passed)
    progress_line = f"  Progress      : {'yes' if result.progress else 'no'}"
    if not result.progress:
        progress_line += f" (unchanged for {result.stagnant_iterations} iteration(s))"

    lines = [
        f"Hanik iteration {result.iteration} complete.",
        f"  Overall score : {result.overall:.2f} ({passed}/{len(result.results)} checks passing)",
        progress_line,
        f"  Open tasks    : {len(result.open_tasks)}",
        f"  Report        : {result.report_path}",
        f"  Brief         : {result.brief_path}",
        f"  State         : {result.state_path}",
    ]
    if result.open_tasks:
        top = result.open_tasks[0]
        lines.append(f"  Next task     : {top.id} - {top.remediation}")
    else:
        lines.append("  Next task     : none open; add a check that raises the bar.")
    if not result.should_continue:
        lines.append("  Continuation  : stopped; a session must act before another run can help.")
    return "\n".join(lines)


def main() -> int:
    """CLI entry point used by the GitHub Actions workflow."""

    try:
        result = run_iteration()
    except MaxIterationsReachedError as exc:
        print(str(exc))
        write_github_output({"status": "max-iterations", "should_continue": "false"})
        return 1

    print(_summarise(result))
    write_github_output(workflow_outputs(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
