"""Rendering of the artifacts each Hanik iteration leaves behind.

Four artifacts are produced per iteration:

* ``reports/iteration-NNNN.html`` -- the human-readable record.
* ``reports/iteration-NNNN.json`` -- the machine-readable companion, so the
  trail can be consumed programmatically instead of scraped.
* ``reports/index.html`` -- an index, so the history is navigable.
* ``state/next-session.md`` -- the brief handed to the next session.

Everything dynamic that reaches HTML goes through :func:`html.escape`. State
is repository-controlled but is deliberately treated as untrusted input: a
string that lands in state must not be able to change how a report renders.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .checks import CRITERIA_DESCRIPTIONS, HANIK_CRITERIA, CheckResult

#: How many open tasks the session brief spells out in full.
BRIEF_TASK_LIMIT = 5

_STYLE = """    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           margin: 2rem auto; max-width: 52rem; line-height: 1.5; color: #1b1f24; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
    th, td { border: 1px solid #d0d7de; padding: 0.4rem 0.6rem; text-align: left;
             vertical-align: top; }
    th { background: #f6f8fa; }
    .pass { color: #0a7d33; font-weight: 600; }
    .fail { color: #b3261e; font-weight: 600; }
    .banner { border-left: 4px solid #b3261e; background: #fff5f5; padding: 0.75rem 1rem;
              margin-bottom: 1.5rem; }
    code { background: #f6f8fa; padding: 0.1rem 0.3rem; border-radius: 3px; }"""


def _fmt(score: float) -> str:
    return f"{score:.2f}"


def _fmt_delta(delta: float) -> str:
    if delta > 0:
        return f"+{delta:.2f}"
    if delta < 0:
        return f"{delta:.2f}"
    return "0.00"


def render_html_report(
    iteration: int,
    timestamp: str,
    scores: Dict[str, float],
    deltas: Dict[str, float],
    overall: float,
    results: Sequence[CheckResult],
    open_tasks: Sequence[CheckResult],
    stagnant_iterations: int,
    progress: bool,
) -> str:
    """Render the human-readable report for one iteration."""

    esc = html.escape
    title = esc(f"Hanik Improvement Loop -- Iteration {iteration}")

    if stagnant_iterations > 0:
        banner = (
            '  <p class="banner"><strong>No measurable progress.</strong> '
            f"The evidence has been identical for {esc(str(stagnant_iterations))} consecutive "
            "iteration(s). The loop cannot improve Hanik on its own: a session must implement "
            "one of the open tasks below, or raise the bar by adding a new check.</p>"
        )
    else:
        banner = ""

    score_rows = []
    for criterion in HANIK_CRITERIA:
        relevant = [r for r in results if r.criterion == criterion]
        passed = sum(1 for r in relevant if r.passed)
        score_rows.append(
            "      <tr>"
            f"<td>{esc(criterion)}</td>"
            f"<td>{esc(_fmt(scores.get(criterion, 0.0)))}</td>"
            f"<td>{esc(_fmt_delta(deltas.get(criterion, 0.0)))}</td>"
            f"<td>{esc(f'{passed}/{len(relevant)}')}</td>"
            f"<td>{esc(CRITERIA_DESCRIPTIONS.get(criterion, ''))}</td>"
            "</tr>"
        )

    evidence_rows = []
    for result in results:
        status = '<span class="pass">pass</span>' if result.passed else '<span class="fail">fail</span>'
        evidence_rows.append(
            "      <tr>"
            f"<td><code>{esc(result.id)}</code></td>"
            f"<td>{status}</td>"
            f"<td>{esc(result.title)}</td>"
            f"<td>{esc(result.evidence)}</td>"
            "</tr>"
        )

    if open_tasks:
        task_items = "\n".join(
            "      <li>"
            f"<code>{esc(task.id)}</code> &mdash; {esc(task.title)}<br>"
            f"<em>{esc(task.evidence)}</em><br>"
            f"{esc(task.remediation)}<br>"
            f"Files: {esc(', '.join(task.targets))}"
            "</li>"
            for task in open_tasks
        )
        tasks_html = f"  <ol>\n{task_items}\n  </ol>"
    else:
        tasks_html = (
            "  <p>Every check passes. The bar is now too low to drive improvement: the next "
            "session must add a new check that Hanik does not yet satisfy.</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
{_STYLE}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p>Generated at {esc(timestamp)} by an automated loop. Overall evidence score:
     <strong>{esc(_fmt(overall))}</strong>
     ({esc(str(sum(1 for r in results if r.passed)))}/{esc(str(len(results)))} checks passing,
     progress this iteration: {esc('yes' if progress else 'no')}).</p>
{banner}
  <h2>Open tasks for the next session</h2>
{tasks_html}

  <h2>Criteria scores</h2>
  <table>
    <thead>
      <tr><th>Criterion</th><th>Score</th><th>Delta</th><th>Checks</th><th>What it means</th></tr>
    </thead>
    <tbody>
{chr(10).join(score_rows)}
    </tbody>
  </table>

  <h2>Evidence</h2>
  <table>
    <thead>
      <tr><th>Check</th><th>Result</th><th>Claim</th><th>Evidence</th></tr>
    </thead>
    <tbody>
{chr(10).join(evidence_rows)}
    </tbody>
  </table>
</body>
</html>
"""


def render_json_report(
    iteration: int,
    timestamp: str,
    scores: Dict[str, float],
    deltas: Dict[str, float],
    overall: float,
    results: Sequence[CheckResult],
    stagnant_iterations: int,
    progress: bool,
) -> Dict[str, Any]:
    """Render the machine-readable companion to the HTML report."""

    return {
        "iteration": iteration,
        "timestamp": timestamp,
        "generated_by": "automated Hanik improvement loop (src/hanik_loop.py)",
        "overall_score": overall,
        "scores": scores,
        "deltas": deltas,
        "progress": progress,
        "stagnant_iterations": stagnant_iterations,
        "checks_passed": sum(1 for result in results if result.passed),
        "checks_total": len(results),
        "checks": [result.as_dict() for result in results],
    }


def render_index_html(reports_dir: Path) -> str:
    """Render an index of every report present in ``reports_dir``."""

    esc = html.escape
    reports = sorted(reports_dir.glob("iteration-*.html"), reverse=True)

    items = []
    for report in reports:
        name = report.name
        payload = report.with_suffix(".json")
        summary = ""
        if payload.is_file():
            try:
                data = json.loads(payload.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict):
                score = data.get("overall_score")
                passed = data.get("checks_passed")
                total = data.get("checks_total")
                if isinstance(score, (int, float)):
                    summary = f" &mdash; score {esc(_fmt(float(score)))}"
                if isinstance(passed, int) and isinstance(total, int):
                    summary += f" ({esc(f'{passed}/{total}')} checks)"
        items.append(f'      <li><a href="{esc(name)}">{esc(name)}</a>{summary}</li>')

    body = "\n".join(items) if items else "      <li>No reports yet.</li>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Hanik Improvement Loop &mdash; report index</title>
  <style>
{_STYLE}
  </style>
</head>
<body>
  <h1>Hanik Improvement Loop &mdash; report index</h1>
  <p>{esc(str(len(reports)))} iteration report(s), newest first. Each report is generated by an
     automated loop and reviewed by a human through a pull request.</p>
  <ul>
{body}
  </ul>
</body>
</html>
"""


def render_session_brief(
    iteration: int,
    timestamp: str,
    scores: Dict[str, float],
    overall: float,
    results: Sequence[CheckResult],
    open_tasks: Sequence[CheckResult],
    stagnant_iterations: int,
    progress: bool,
) -> str:
    """Render the brief the next session reads before doing anything.

    Each loop run happens in a fresh session with no memory of the previous
    one, so this file is the entire handover: what the state of Hanik is, what
    is demonstrably missing, and which single task to pick up first.
    """

    passed = sum(1 for result in results if result.passed)
    lines: List[str] = [
        "# Next session brief",
        "",
        f"Generated by iteration {iteration} at {timestamp}.",
        "",
        f"- Overall evidence score: **{_fmt(overall)}** ({passed}/{len(results)} checks passing)",
        f"- Progress in the last iteration: **{'yes' if progress else 'no'}**",
        f"- Consecutive iterations without measurable change: **{stagnant_iterations}**",
        f"- Open tasks: **{len(open_tasks)}**",
        "",
        "## Scores",
        "",
        "| Criterion | Score | Checks passing |",
        "| --- | --- | --- |",
    ]

    for criterion in HANIK_CRITERIA:
        relevant = [r for r in results if r.criterion == criterion]
        criterion_passed = sum(1 for r in relevant if r.passed)
        lines.append(
            f"| {criterion} | {_fmt(scores.get(criterion, 0.0))} | {criterion_passed}/{len(relevant)} |"
        )

    lines += ["", "## Do this next", ""]

    if not open_tasks:
        lines += [
            "Every check passes, which means the bar is too low, not that Hanik is finished.",
            "",
            "Pick one capability Hanik genuinely lacks, add a check for it to `src/checks.py`",
            "with concrete `remediation` and `targets`, and let the next iteration fail it. Do not",
            "weaken an existing check to create work.",
        ]
    else:
        lines += [
            "Implement the first task below. Do exactly one, and do it properly — a session",
            "that fixes one thing for real is worth more than one that touches five superficially.",
            "",
        ]
        for position, task in enumerate(open_tasks[:BRIEF_TASK_LIMIT], start=1):
            lines += [
                f"### {position}. `{task.id}` ({task.criterion})",
                "",
                f"- **Claim that fails:** {task.title}",
                f"- **Evidence:** {task.evidence}",
                f"- **Do:** {task.remediation}",
                f"- **Files:** {', '.join(task.targets)}",
                "",
            ]
        remaining = len(open_tasks) - BRIEF_TASK_LIMIT
        if remaining > 0:
            lines += [f"_{remaining} further open task(s) are listed in this iteration's report._", ""]

    if stagnant_iterations > 0:
        lines += [
            "## Warning",
            "",
            f"The evidence has not changed for {stagnant_iterations} iteration(s). Re-running the",
            "loop will not help. Either implement a task above or stop the chain and escalate to a",
            "human.",
            "",
        ]

    lines += [
        "## Rules",
        "",
        "- Change the artifact, not the check. Editing `src/checks.py` to make a failing check pass",
        "  without building the capability is the one failure mode this loop cannot detect on its",
        "  own, and it is the reason the previous scoring model was replaced.",
        "- Run `python3 -m pytest tests/ -v` before finishing.",
        "- Run `python3 -m src.hanik_loop` last, so the report and this brief reflect your change.",
        "- Full contract: `AGENTS.md`.",
        "",
    ]

    return "\n".join(lines)
