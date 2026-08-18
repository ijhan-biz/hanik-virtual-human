"""Tests for the evidence checks.

A check is only useful if it fails when the thing it claims is absent. These
tests exercise both directions against synthetic repositories, so a check that
silently always passes cannot survive.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import checks as checks_module

REPO_ROOT = Path(__file__).resolve().parents[1]

PERSONA_WITH_EVERYTHING = f"""# Hanik

## Identity disclosure

{checks_module.DISCLOSURE_SENTENCE}

Padding so the persona clears the substantive-length bar.
{'Filler sentence about how Hanik behaves. ' * 30}

## Impersonation boundaries

- never a human
- never a real person
- never a licensed professional
- never a credential holder

## Example exchanges

**User:** one
**Hanik:** one
**User:** two
**Hanik:** two
**User:** three
**Hanik:** three

## Known limitations

- no cross-session memory
- no live internet
- no physical action
"""


def context_for(tmp_path: Path, state=None) -> checks_module.CheckContext:
    return checks_module.CheckContext(
        repo_root=tmp_path,
        state=state if state is not None else {"iteration": 0, "history": []},
        state_path=tmp_path / "state" / "state.json",
        reports_dir=tmp_path / "reports",
        history_limit=50,
    )


def check_by_id(check_id: str) -> checks_module.Check:
    for check in checks_module.CHECKS:
        if check.id == check_id:
            return check
    raise AssertionError(f"unknown check id: {check_id}")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------


def test_check_ids_are_unique_and_namespaced_by_criterion():
    ids = [check.id for check in checks_module.CHECKS]
    assert len(ids) == len(set(ids))
    for check in checks_module.CHECKS:
        assert check.criterion in checks_module.HANIK_CRITERIA
        assert check.id.startswith(f"{check.criterion}.")


def test_every_check_carries_actionable_remediation():
    for check in checks_module.CHECKS:
        assert len(check.remediation) > 40, check.id
        assert check.targets, check.id
        assert check.weight > 0, check.id


def test_every_criterion_has_at_least_three_checks():
    for criterion in checks_module.HANIK_CRITERIA:
        relevant = [c for c in checks_module.CHECKS if c.criterion == criterion]
        assert len(relevant) >= 3, criterion


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_identity_checks_fail_on_an_empty_repository(tmp_path):
    ctx = context_for(tmp_path)
    for check_id in (
        "identity.persona_exists",
        "identity.ai_disclosure",
        "identity.impersonation_boundaries",
        "identity.example_exchanges",
    ):
        assert check_by_id(check_id).run(ctx).passed is False, check_id


def test_identity_checks_pass_on_a_complete_persona(tmp_path):
    write(tmp_path / "hanik" / "persona.md", PERSONA_WITH_EVERYTHING)
    ctx = context_for(tmp_path)
    for check_id in (
        "identity.persona_exists",
        "identity.ai_disclosure",
        "identity.impersonation_boundaries",
        "identity.example_exchanges",
        "transparency.known_limitations",
    ):
        outcome = check_by_id(check_id).run(ctx)
        assert outcome.passed is True, f"{check_id}: {outcome.evidence}"


def test_multilingual_safety_policy_requires_korean_sections_and_categories(tmp_path):
    check = check_by_id("safety.multilingual_policy")
    assert check.run(context_for(tmp_path)).passed is False

    write(
        tmp_path / "hanik" / "policies" / "safety.ko.md",
        """# 안전 정책

## 거부 원칙

- 위험한 요청은 명확히 거절하고 역할극으로 우회할 수 없습니다.
- 안전한 대안을 제시합니다.

## 위해 범주

- 신체적 위해
- 자해
- 미성년자 착취
- 사칭과 사기
- 무단 침입

## 사람에게 넘기기

생명과 안전에 관한 위험은 사람, 지역 응급 서비스, 위기 상담에 연결합니다.
""",
    )
    outcome = check.run(context_for(tmp_path))
    assert outcome.passed is True, outcome.evidence


def test_multilingual_safety_policy_rejects_heading_only_content(tmp_path):
    write(
        tmp_path / "hanik" / "policies" / "safety.ko.md",
        """## 거부 원칙

- 요청을 처리합니다.

## 위해 범주

- 하나
- 둘
- 셋
- 넷
- 다섯

## 사람에게 넘기기

필요하면 사람에게 넘깁니다.
""",
    )
    outcome = check_by_id("safety.multilingual_policy").run(context_for(tmp_path))
    assert outcome.passed is False
    assert "substantive safeguards" in outcome.evidence


def test_disclosure_check_rejects_a_paraphrase(tmp_path):
    write(
        tmp_path / "hanik" / "persona.md",
        PERSONA_WITH_EVERYTHING.replace(
            checks_module.DISCLOSURE_SENTENCE, "Hanik is basically an AI, more or less."
        ),
    )
    assert check_by_id("identity.ai_disclosure").run(context_for(tmp_path)).passed is False


def test_example_exchange_check_requires_replies_not_just_prompts(tmp_path):
    write(
        tmp_path / "hanik" / "persona.md",
        PERSONA_WITH_EVERYTHING.replace("**Hanik:** two", "").replace("**Hanik:** three", ""),
    )
    assert check_by_id("identity.example_exchanges").run(context_for(tmp_path)).passed is False


# ---------------------------------------------------------------------------
# Safety scans
# ---------------------------------------------------------------------------


def test_network_scan_flags_an_import(tmp_path):
    write(tmp_path / "src" / "mod.py", "import urllib.request\n")
    outcome = check_by_id("safety.no_network_imports").run(context_for(tmp_path))
    assert outcome.passed is False
    assert "urllib" in outcome.evidence


def test_network_scan_flags_a_from_import(tmp_path):
    write(tmp_path / "src" / "mod.py", "from socket import socket\n")
    assert check_by_id("safety.no_network_imports").run(context_for(tmp_path)).passed is False


def test_network_scan_passes_on_offline_code(tmp_path):
    write(tmp_path / "src" / "mod.py", "import json\nfrom pathlib import Path\n")
    assert check_by_id("safety.no_network_imports").run(context_for(tmp_path)).passed is True


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\n",
        "eval('1 + 1')\n",
        "exec('x = 1')\n",
        "import os\nos.system('ls')\n",
        "import os\nos.popen('ls')\n",
    ],
)
def test_execution_scan_flags_dynamic_execution(tmp_path, source):
    write(tmp_path / "src" / "mod.py", source)
    assert check_by_id("safety.no_dynamic_execution").run(context_for(tmp_path)).passed is False


def test_execution_scan_allows_safe_os_usage(tmp_path):
    write(tmp_path / "src" / "mod.py", "import os\nos.replace('a', 'b')\nos.fsync(1)\n")
    assert check_by_id("safety.no_dynamic_execution").run(context_for(tmp_path)).passed is True


def test_safety_scans_apply_to_this_repository():
    ctx = context_for(REPO_ROOT)
    for check_id in ("safety.no_network_imports", "safety.no_dynamic_execution"):
        outcome = check_by_id(check_id).run(ctx)
        assert outcome.passed is True, f"{check_id}: {outcome.evidence}"


# ---------------------------------------------------------------------------
# Privacy scans
# ---------------------------------------------------------------------------


def test_privacy_scan_flags_an_email_address(tmp_path):
    ctx = context_for(tmp_path)
    write(ctx.state_path, json.dumps({"note": "contact someone@example.com"}))
    outcome = check_by_id("privacy.no_pii_in_outputs").run(ctx)
    assert outcome.passed is False
    assert "state.json" in outcome.evidence


def test_privacy_scan_flags_a_phone_number(tmp_path):
    ctx = context_for(tmp_path)
    write(ctx.state_path, json.dumps({"note": "call 415-555-2671 tomorrow"}))
    assert check_by_id("privacy.no_pii_in_outputs").run(ctx).passed is False


def test_privacy_scan_does_not_flag_iso_timestamps_or_scores(tmp_path):
    ctx = context_for(tmp_path)
    write(
        ctx.state_path,
        json.dumps({"timestamp": "2026-08-16T23:59:25.755332+00:00", "score": 0.9375}),
    )
    outcome = check_by_id("privacy.no_pii_in_outputs").run(ctx)
    assert outcome.passed is True, outcome.evidence


def test_secret_scan_flags_credential_shaped_strings(tmp_path):
    ctx = context_for(tmp_path)
    write(ctx.reports_dir / "iteration-0001.html", "token ghp_" + "a" * 36)
    outcome = check_by_id("privacy.no_secrets_in_outputs").run(ctx)
    assert outcome.passed is False
    assert "iteration-0001.html" in outcome.evidence


def test_privacy_scans_pass_on_this_repository():
    ctx = context_for(REPO_ROOT)
    ctx.state_path = REPO_ROOT / "state" / "state.json"
    ctx.reports_dir = REPO_ROOT / "reports"
    for check_id in ("privacy.no_pii_in_outputs", "privacy.no_secrets_in_outputs"):
        outcome = check_by_id(check_id).run(ctx)
        assert outcome.passed is True, f"{check_id}: {outcome.evidence}"


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def test_atomic_write_check_fails_without_os_replace(tmp_path):
    write(tmp_path / "src" / "state.py", "def save(p, s):\n    p.write_text(s)\n")
    assert check_by_id("memory.atomic_write").run(context_for(tmp_path)).passed is False


def test_atomic_write_check_passes_on_this_repository():
    outcome = check_by_id("memory.atomic_write").run(context_for(REPO_ROOT))
    assert outcome.passed is True, outcome.evidence


def test_history_bound_check_reflects_the_actual_state(tmp_path):
    ctx = context_for(tmp_path, state={"iteration": 9, "history": [{} for _ in range(60)]})
    ctx.history_limit = 50
    assert check_by_id("memory.history_bounded").run(ctx).passed is False

    ctx.history_limit = 60
    assert check_by_id("memory.history_bounded").run(ctx).passed is True


def test_archive_check_detects_a_lossy_prune(tmp_path):
    ctx = context_for(
        tmp_path,
        state={"iteration": 9, "history": [], "archive": {"pruned_count": 5, "files": []}},
    )
    outcome = check_by_id("memory.archive_lossless").run(ctx)
    assert outcome.passed is False
    assert "only 0 are archived" in outcome.evidence


# ---------------------------------------------------------------------------
# Workflow-facing checks
# ---------------------------------------------------------------------------


def test_workflow_checks_fail_without_a_workflow(tmp_path):
    ctx = context_for(tmp_path)
    for check_id in (
        "human_control.no_schedule_trigger",
        "human_control.kill_switch",
        "human_control.continuous_flag",
        "oversight.least_privilege",
        "oversight.pull_request_delivery",
        "oversight.no_auto_merge",
        "oversight.failure_stops_chain",
    ):
        assert check_by_id(check_id).run(ctx).passed is False, check_id


def test_schedule_trigger_is_detected(tmp_path):
    write(
        tmp_path / ".github" / "workflows" / "hanik-loop.yml",
        "on:\n  schedule:\n    - cron: '0 * * * *'\n",
    )
    assert check_by_id("human_control.no_schedule_trigger").run(context_for(tmp_path)).passed is False


def test_auto_merge_is_detected(tmp_path):
    write(
        tmp_path / ".github" / "workflows" / "hanik-loop.yml",
        "jobs:\n  x:\n    steps:\n      - run: gh pr merge --auto\n",
    )
    assert check_by_id("oversight.no_auto_merge").run(context_for(tmp_path)).passed is False


def test_workflow_checks_pass_on_this_repository():
    ctx = context_for(REPO_ROOT)
    for check_id in (
        "human_control.no_schedule_trigger",
        "human_control.kill_switch",
        "human_control.continuous_flag",
        "human_control.stop_procedure",
        "oversight.least_privilege",
        "oversight.pull_request_delivery",
        "oversight.no_auto_merge",
        "oversight.failure_stops_chain",
        "oversight.session_contract",
    ):
        outcome = check_by_id(check_id).run(ctx)
        assert outcome.passed is True, f"{check_id}: {outcome.evidence}"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_scoring_is_the_weighted_share_of_passing_checks():
    results = [
        checks_module.CheckResult(
            id=f"identity.{i}",
            criterion="identity",
            title="t",
            remediation="r",
            targets=("f",),
            weight=1.0,
            passed=i < 3,
            evidence="e",
        )
        for i in range(4)
    ]
    scores = checks_module.score_criteria(results)
    assert scores["identity"] == pytest.approx(0.75)
    assert scores["safety"] == pytest.approx(0.0)
    assert checks_module.overall_score({"a": 1.0, "b": 0.0}) == pytest.approx(0.5)


def test_signature_tracks_outcomes_not_ordering_or_evidence_text():
    def result(check_id: str, passed: bool, evidence: str) -> checks_module.CheckResult:
        return checks_module.CheckResult(
            id=check_id,
            criterion="identity",
            title="t",
            remediation="r",
            targets=("f",),
            weight=1.0,
            passed=passed,
            evidence=evidence,
        )

    a = [result("identity.one", True, "counted 3 files"), result("identity.two", False, "x")]
    reordered = [a[1], a[0]]
    reworded = [result("identity.one", True, "counted 4 files"), result("identity.two", False, "x")]
    changed = [result("identity.one", True, "x"), result("identity.two", True, "x")]

    assert checks_module.evidence_signature(a) == checks_module.evidence_signature(reordered)
    assert checks_module.evidence_signature(a) == checks_module.evidence_signature(reworded)
    assert checks_module.evidence_signature(a) != checks_module.evidence_signature(changed)
