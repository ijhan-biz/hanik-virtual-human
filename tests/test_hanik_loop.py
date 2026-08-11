"""Tests for the Hanik virtual-human improvement loop."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import hanik_loop as loop


@pytest.fixture()
def workdir(tmp_path: Path):
    state_path = tmp_path / "state" / "state.json"
    reports_dir = tmp_path / "reports"
    return state_path, reports_dir


def test_first_iteration_creates_report_and_state(workdir):
    state_path, reports_dir = workdir

    result = loop.run_iteration(state_path=state_path, reports_dir=reports_dir)

    assert result.iteration == 1
    assert result.report_path.exists()
    assert state_path.exists()

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["iteration"] == 1
    assert len(saved["history"]) == 1
    assert saved["history"][0]["iteration"] == 1

    # Every criterion should be present with the baseline score.
    for criterion in loop.HANIK_CRITERIA:
        assert criterion in result.scores
        assert result.scores[criterion] == loop.BASE_SCORE

    # All criteria start below target, so recommendations should exist.
    assert len(result.recommendations) == len(loop.HANIK_CRITERIA)


def test_second_iteration_improves_recommended_criteria(workdir):
    state_path, reports_dir = workdir

    first = loop.run_iteration(state_path=state_path, reports_dir=reports_dir)
    second = loop.run_iteration(state_path=state_path, reports_dir=reports_dir)

    assert second.iteration == 2
    recommended_criteria = {rec["criterion"] for rec in first.recommendations}
    for criterion in recommended_criteria:
        assert second.scores[criterion] == pytest.approx(
            loop.BASE_SCORE + loop.IMPROVEMENT_STEP
        )


def test_scores_never_exceed_max_score(workdir):
    state_path, reports_dir = workdir

    # Run enough iterations that scores would exceed MAX_SCORE without the cap.
    iterations_needed = int((loop.MAX_SCORE - loop.BASE_SCORE) / loop.IMPROVEMENT_STEP) + 5
    result = None
    for _ in range(iterations_needed):
        result = loop.run_iteration(state_path=state_path, reports_dir=reports_dir)

    assert result is not None
    for score in result.scores.values():
        assert score <= loop.MAX_SCORE


def test_html_report_escapes_untrusted_state_content(workdir):
    state_path, reports_dir = workdir
    state_path.parent.mkdir(parents=True, exist_ok=True)

    malicious_state = {
        "iteration": 1,
        "history": [
            {
                "iteration": 1,
                "timestamp": "2024-01-01T00:00:00+00:00",
                "scores": {c: 0.5 for c in loop.HANIK_CRITERIA},
                "recommendations": [
                    {
                        "criterion": "identity",
                        "score": 0.5,
                        "recommendation": "<script>alert('xss')</script>",
                    }
                ],
                "report_path": "reports/iteration-0001.html",
            }
        ],
    }
    state_path.write_text(json.dumps(malicious_state), encoding="utf-8")

    result = loop.run_iteration(state_path=state_path, reports_dir=reports_dir)

    html_content = result.report_path.read_text(encoding="utf-8")
    assert "<script>" not in html_content
    assert "&lt;script&gt;" in html_content


def test_render_html_report_is_escaped_directly():
    scores = {c: 0.1 for c in loop.HANIK_CRITERIA}
    recommendations = [
        {
            "criterion": "identity",
            "score": 0.1,
            "recommendation": "<img src=x onerror=alert(1)>",
        }
    ]
    html_content = loop.render_html_report("1", "2024-01-01T00:00:00+00:00", scores, recommendations)

    assert "<img src=x onerror=alert(1)>" not in html_content
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_content


def test_corrupted_state_file_recovers_to_fresh_state(workdir):
    state_path, reports_dir = workdir
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not valid json!!", encoding="utf-8")

    result = loop.run_iteration(state_path=state_path, reports_dir=reports_dir)

    assert result.iteration == 1
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["iteration"] == 1


def test_state_file_with_wrong_shape_recovers_to_fresh_state(workdir):
    state_path, reports_dir = workdir
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    state = loop.load_state(state_path)
    assert state == {"iteration": 0, "history": []}

    state_path.write_text(json.dumps({"iteration": "bad", "history": []}), encoding="utf-8")
    state = loop.load_state(state_path)
    assert state == {"iteration": 0, "history": []}


def test_save_state_atomic_leaves_no_temp_files(workdir):
    state_path, _ = workdir
    loop.save_state_atomic({"iteration": 1, "history": []}, state_path)

    assert state_path.exists()
    leftover_tmp = list(state_path.parent.glob(".state-*.tmp"))
    assert leftover_tmp == []


def test_save_state_atomic_never_leaves_partial_file_on_readback(workdir):
    state_path, _ = workdir
    for i in range(5):
        loop.save_state_atomic({"iteration": i, "history": []}, state_path)
        # The file must always be valid, complete JSON after each write.
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["iteration"] == i


def test_max_iterations_guard_blocks_further_runs(workdir):
    state_path, reports_dir = workdir

    loop.run_iteration(state_path=state_path, reports_dir=reports_dir, max_iterations=2)
    loop.run_iteration(state_path=state_path, reports_dir=reports_dir, max_iterations=2)

    with pytest.raises(loop.MaxIterationsReachedError):
        loop.run_iteration(state_path=state_path, reports_dir=reports_dir, max_iterations=2)

    # State must not have been advanced past the guard.
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["iteration"] == 2


def test_get_max_iterations_defaults_and_validates(monkeypatch):
    monkeypatch.delenv(loop.MAX_ITERATIONS_ENV_VAR, raising=False)
    assert loop.get_max_iterations() == loop.DEFAULT_MAX_ITERATIONS

    monkeypatch.setenv(loop.MAX_ITERATIONS_ENV_VAR, "not-a-number")
    assert loop.get_max_iterations() == loop.DEFAULT_MAX_ITERATIONS

    monkeypatch.setenv(loop.MAX_ITERATIONS_ENV_VAR, "-5")
    assert loop.get_max_iterations() == loop.DEFAULT_MAX_ITERATIONS

    monkeypatch.setenv(loop.MAX_ITERATIONS_ENV_VAR, "0")
    assert loop.get_max_iterations() == loop.DEFAULT_MAX_ITERATIONS

    monkeypatch.setenv(loop.MAX_ITERATIONS_ENV_VAR, "7")
    assert loop.get_max_iterations() == 7


def test_run_iteration_uses_env_max_iterations_when_not_overridden(workdir, monkeypatch):
    state_path, reports_dir = workdir
    monkeypatch.setenv(loop.MAX_ITERATIONS_ENV_VAR, "1")

    loop.run_iteration(state_path=state_path, reports_dir=reports_dir)

    with pytest.raises(loop.MaxIterationsReachedError):
        loop.run_iteration(state_path=state_path, reports_dir=reports_dir)


def test_recommendations_stop_once_target_score_reached(workdir):
    state_path, reports_dir = workdir

    # Manually seed a state where every criterion already meets target.
    state_path.parent.mkdir(parents=True, exist_ok=True)
    seeded_state = {
        "iteration": 1,
        "history": [
            {
                "iteration": 1,
                "timestamp": "2024-01-01T00:00:00+00:00",
                "scores": {c: loop.TARGET_SCORE for c in loop.HANIK_CRITERIA},
                "recommendations": [],
                "report_path": "reports/iteration-0001.html",
            }
        ],
    }
    state_path.write_text(json.dumps(seeded_state), encoding="utf-8")

    result = loop.run_iteration(state_path=state_path, reports_dir=reports_dir)

    assert result.recommendations == []
    assert "All criteria meet or exceed the target score." in result.report_path.read_text(
        encoding="utf-8"
    )
