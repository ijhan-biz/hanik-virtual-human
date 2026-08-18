"""Tests for the Hanik improvement loop orchestration.

The loop's contract is that a score can only move when the repository moves.
These tests pin that contract down with a synthetic check set, so a run is
fully deterministic, plus a smoke test against the real repository.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import checks as checks_module
from src import hanik_loop as loop
from src import state as state_module

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def workdir(tmp_path: Path):
    return tmp_path / "state" / "state.json", tmp_path / "reports"


def make_check(check_id: str, criterion: str, passes: bool) -> checks_module.Check:
    """Build a check with a fixed outcome, so signatures are deterministic."""

    def run(_ctx: checks_module.CheckContext) -> checks_module.Outcome:
        return checks_module.Outcome(passes, f"synthetic evidence for {check_id}")

    return checks_module.Check(
        id=check_id,
        criterion=criterion,
        title=f"Synthetic claim {check_id}",
        remediation=f"Do the work behind {check_id}.",
        targets=("hanik/persona.md",),
        run=run,
    )


PASSING_TWO = (
    make_check("identity.one", "identity", True),
    make_check("identity.two", "identity", True),
)

ONE_OF_TWO = (
    make_check("identity.one", "identity", True),
    make_check("identity.two", "identity", False),
)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def test_iteration_writes_all_four_artifacts(workdir):
    state_path, reports_dir = workdir

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )

    assert result.iteration == 1
    assert result.report_path.is_file()
    assert result.json_report_path.is_file()
    assert result.index_path.is_file()
    assert result.brief_path.is_file()
    assert state_path.is_file()

    payload = json.loads(result.json_report_path.read_text(encoding="utf-8"))
    assert payload["iteration"] == 1
    assert payload["checks_total"] == 2
    assert payload["checks_passed"] == 1
    assert {check["id"] for check in payload["checks"]} == {"identity.one", "identity.two"}

    assert "iteration-0001.html" in result.index_path.read_text(encoding="utf-8")
    assert "## Do this next" in result.brief_path.read_text(encoding="utf-8")


def test_brief_names_the_failing_check_and_its_remediation(workdir):
    state_path, reports_dir = workdir

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )

    brief = result.brief_path.read_text(encoding="utf-8")
    assert "identity.two" in brief
    assert "Do the work behind identity.two." in brief
    assert "identity.one" not in brief.split("## Do this next")[1]


def test_brief_demands_a_harder_check_when_everything_passes(workdir):
    state_path, reports_dir = workdir

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=PASSING_TWO
    )

    assert result.open_tasks == []
    brief = result.brief_path.read_text(encoding="utf-8")
    assert "the bar is too low" in brief
    assert "add a check for it" in brief
    # Nothing left to do means nothing is gained by running again.
    assert result.should_continue is False


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_is_the_share_of_passing_evidence(workdir):
    state_path, reports_dir = workdir

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )

    assert result.scores["identity"] == pytest.approx(0.5)
    # A criterion with no evidence scores zero rather than being assumed good.
    assert result.scores["safety"] == pytest.approx(0.0)


def test_score_does_not_move_when_the_repository_does_not(workdir):
    state_path, reports_dir = workdir

    first = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )
    second = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )

    assert second.scores == first.scores
    assert all(delta == 0.0 for delta in second.deltas.values())


def test_score_moves_only_when_evidence_changes(workdir):
    state_path, reports_dir = workdir

    loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )
    improved = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=PASSING_TWO
    )

    assert improved.scores["identity"] == pytest.approx(1.0)
    assert improved.deltas["identity"] == pytest.approx(0.5)
    assert improved.progress is True


# ---------------------------------------------------------------------------
# Stagnation
# ---------------------------------------------------------------------------


def test_repeated_identical_evidence_is_reported_as_stagnation(workdir):
    state_path, reports_dir = workdir

    first = loop.run_iteration(
        state_path=state_path,
        reports_dir=reports_dir,
        repo_root=REPO_ROOT,
        checks=ONE_OF_TWO,
        stagnation_limit=2,
    )
    second = loop.run_iteration(
        state_path=state_path,
        reports_dir=reports_dir,
        repo_root=REPO_ROOT,
        checks=ONE_OF_TWO,
        stagnation_limit=2,
    )
    third = loop.run_iteration(
        state_path=state_path,
        reports_dir=reports_dir,
        repo_root=REPO_ROOT,
        checks=ONE_OF_TWO,
        stagnation_limit=2,
    )

    assert (first.progress, first.stagnant_iterations) == (True, 0)
    assert (second.progress, second.stagnant_iterations) == (False, 1)
    assert (third.progress, third.stagnant_iterations) == (False, 2)

    # The chain keeps going while it is still learning something, and stops
    # once it demonstrably is not.
    assert first.should_continue is True
    assert second.should_continue is True
    assert third.should_continue is False

    assert "No measurable progress" in third.report_path.read_text(encoding="utf-8")
    assert "## Warning" in third.brief_path.read_text(encoding="utf-8")


def test_progress_resets_the_stagnation_counter(workdir):
    state_path, reports_dir = workdir

    for _ in range(2):
        loop.run_iteration(
            state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
        )
    recovered = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=PASSING_TWO
    )

    assert recovered.progress is True
    assert recovered.stagnant_iterations == 0
    assert recovered.state["stagnant_iterations"] == 0


def test_continuation_can_be_disabled_by_a_human(workdir, monkeypatch):
    state_path, reports_dir = workdir
    monkeypatch.setenv(loop.CONTINUOUS_ENV_VAR, "false")

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )

    assert result.open_tasks
    assert result.should_continue is False


# ---------------------------------------------------------------------------
# Report safety
# ---------------------------------------------------------------------------


def test_html_report_escapes_untrusted_check_evidence(workdir):
    state_path, reports_dir = workdir
    hostile = (
        make_check("identity.one", "identity", True),
        checks_module.Check(
            id="identity.hostile",
            criterion="identity",
            title="<script>alert('title')</script>",
            remediation="<img src=x onerror=alert(1)>",
            targets=("<b>targets</b>",),
            run=lambda _ctx: checks_module.Outcome(False, "<script>alert('evidence')</script>"),
        ),
    )

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=hostile
    )

    html_content = result.report_path.read_text(encoding="utf-8")
    assert "<script>alert('evidence')</script>" not in html_content
    assert "&lt;script&gt;alert(&#x27;evidence&#x27;)&lt;/script&gt;" in html_content
    assert "<img src=x onerror=alert(1)>" not in html_content
    assert "<b>targets</b>" not in html_content


def test_report_index_escapes_and_survives_a_broken_json_companion(workdir):
    state_path, reports_dir = workdir
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "iteration-0999.html").write_text("<p>old</p>", encoding="utf-8")
    (reports_dir / "iteration-0999.json").write_text("{not json", encoding="utf-8")

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )

    index = result.index_path.read_text(encoding="utf-8")
    assert "iteration-0999.html" in index
    assert "iteration-0001.html" in index


def test_a_raising_check_fails_loudly_instead_of_passing_silently(workdir):
    state_path, reports_dir = workdir

    def explode(_ctx):
        raise RuntimeError("check is broken")

    broken = (
        checks_module.Check(
            id="identity.broken",
            criterion="identity",
            title="Broken check",
            remediation="Fix the check.",
            targets=("src/checks.py",),
            run=explode,
        ),
    )

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=broken
    )

    assert result.scores["identity"] == pytest.approx(0.0)
    assert result.open_tasks[0].id == "identity.broken"
    assert "RuntimeError" in result.open_tasks[0].evidence


# ---------------------------------------------------------------------------
# State durability
# ---------------------------------------------------------------------------


def test_corrupted_state_file_recovers_to_a_fresh_state(workdir):
    state_path, reports_dir = workdir
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not valid json!!", encoding="utf-8")

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )

    assert result.iteration == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["iteration"] == 1


def test_structurally_invalid_state_recovers_to_a_fresh_state(workdir):
    state_path, _ = workdir
    state_path.parent.mkdir(parents=True, exist_ok=True)

    state_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert state_module.load_state(state_path) == state_module.empty_state()

    state_path.write_text(json.dumps({"iteration": "bad", "history": []}), encoding="utf-8")
    assert state_module.load_state(state_path) == state_module.empty_state()

    state_path.write_text(json.dumps({"iteration": -1, "history": []}), encoding="utf-8")
    assert state_module.load_state(state_path) == state_module.empty_state()

    state_path.write_text(json.dumps({"iteration": 3, "history": "nope"}), encoding="utf-8")
    assert state_module.load_state(state_path) == state_module.empty_state()


def test_legacy_state_is_migrated_rather_than_discarded(workdir):
    state_path, _ = workdir
    state_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "iteration": 250,
        "history": [{"iteration": 250, "scores": {"identity": 0.9}, "recommendations": []}],
    }
    state_path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = state_module.load_state(state_path)

    assert migrated["iteration"] == 250
    assert len(migrated["history"]) == 1
    assert migrated["schema_version"] == state_module.SCHEMA_VERSION
    assert migrated["stagnant_iterations"] == 0
    assert migrated["archive"] == {"pruned_count": 0, "files": []}


def test_state_writes_are_atomic_and_leave_no_temp_files(workdir):
    state_path, _ = workdir

    for i in range(5):
        state_module.save_state_atomic({"iteration": i, "history": []}, state_path)
        assert json.loads(state_path.read_text(encoding="utf-8"))["iteration"] == i

    assert list(state_path.parent.glob(".state-*.tmp")) == []


def test_history_is_pruned_into_a_lossless_archive(workdir):
    state_path, reports_dir = workdir

    for _ in range(6):
        result = loop.run_iteration(
            state_path=state_path,
            reports_dir=reports_dir,
            repo_root=REPO_ROOT,
            checks=ONE_OF_TWO,
            history_limit=3,
        )

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["iteration"] == 6
    assert len(saved["history"]) == 3
    assert [entry["iteration"] for entry in saved["history"]] == [4, 5, 6]

    assert saved["archive"]["pruned_count"] == 3
    assert state_module.archived_entry_count(state_path) == 3

    archived_iterations = []
    for archive_file in sorted(state_module.archive_dir_for(state_path).glob("history-*.json")):
        payload = json.loads(archive_file.read_text(encoding="utf-8"))
        archived_iterations += [entry["iteration"] for entry in payload["entries"]]
    assert sorted(archived_iterations) == [1, 2, 3]
    assert result.state["archive"]["files"]


def test_history_limit_env_var_is_validated(monkeypatch):
    monkeypatch.delenv(state_module.HISTORY_LIMIT_ENV_VAR, raising=False)
    assert state_module.get_history_limit() == state_module.DEFAULT_HISTORY_LIMIT

    for bad in ("not-a-number", "0", "-4"):
        monkeypatch.setenv(state_module.HISTORY_LIMIT_ENV_VAR, bad)
        assert state_module.get_history_limit() == state_module.DEFAULT_HISTORY_LIMIT

    monkeypatch.setenv(state_module.HISTORY_LIMIT_ENV_VAR, "7")
    assert state_module.get_history_limit() == 7


# ---------------------------------------------------------------------------
# Bounds and workflow contract
# ---------------------------------------------------------------------------


def test_max_iterations_guard_blocks_further_runs(workdir):
    state_path, reports_dir = workdir

    for _ in range(2):
        loop.run_iteration(
            state_path=state_path,
            reports_dir=reports_dir,
            repo_root=REPO_ROOT,
            checks=ONE_OF_TWO,
            max_iterations=2,
        )

    with pytest.raises(loop.MaxIterationsReachedError):
        loop.run_iteration(
            state_path=state_path,
            reports_dir=reports_dir,
            repo_root=REPO_ROOT,
            checks=ONE_OF_TWO,
            max_iterations=2,
        )

    assert json.loads(state_path.read_text(encoding="utf-8"))["iteration"] == 2


def test_iteration_bound_env_vars_are_validated(monkeypatch):
    for name, getter, default in (
        (loop.MAX_ITERATIONS_ENV_VAR, loop.get_max_iterations, loop.DEFAULT_MAX_ITERATIONS),
        (loop.STAGNATION_LIMIT_ENV_VAR, loop.get_stagnation_limit, loop.DEFAULT_STAGNATION_LIMIT),
    ):
        monkeypatch.delenv(name, raising=False)
        assert getter() == default

        for bad in ("not-a-number", "0", "-5"):
            monkeypatch.setenv(name, bad)
            assert getter() == default

        monkeypatch.setenv(name, "9")
        assert getter() == 9


def test_workflow_outputs_are_written_for_actions(workdir, tmp_path):
    state_path, reports_dir = workdir

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT, checks=ONE_OF_TWO
    )
    output_file = tmp_path / "gh-output"
    assert loop.write_github_output(loop.workflow_outputs(result), str(output_file)) is True

    written = dict(
        line.split("=", 1) for line in output_file.read_text(encoding="utf-8").splitlines() if line
    )
    assert written["status"] == "success"
    assert written["iteration"] == "1"
    assert written["open_tasks"] == "1"
    assert written["checks_total"] == "2"
    assert written["should_continue"] == "true"


def test_workflow_output_is_skipped_outside_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert loop.write_github_output({"status": "success"}) is False


# ---------------------------------------------------------------------------
# Smoke test against the real repository
# ---------------------------------------------------------------------------


def test_real_checks_run_against_this_repository(workdir):
    state_path, reports_dir = workdir

    result = loop.run_iteration(
        state_path=state_path, reports_dir=reports_dir, repo_root=REPO_ROOT
    )

    assert len(result.results) == len(checks_module.CHECKS)
    assert set(result.scores) == set(checks_module.HANIK_CRITERIA)
    assert all(0.0 <= score <= 1.0 for score in result.scores.values())

    # Every criterion score must equal the share of its checks that passed:
    # the score cannot drift away from the evidence behind it.
    for criterion in checks_module.HANIK_CRITERIA:
        relevant = [r for r in result.results if r.criterion == criterion]
        expected = sum(1 for r in relevant if r.passed) / len(relevant)
        assert result.scores[criterion] == pytest.approx(expected, abs=1e-4)

    assert result.open_tasks == [r for r in result.results if not r.passed]
