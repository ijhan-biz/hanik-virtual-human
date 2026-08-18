"""Adversarial regression cases for Hanik's persona and safety policy.

These tests exercise the text that protects Hanik when a request tries to
override identity disclosure, borrow authority, or turn a dangerous request
into role-play. They are intentionally small and offline so they can run in
every improvement iteration.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERSONA = (ROOT / "hanik" / "persona.md").read_text(encoding="utf-8")
PERSONA_KO = (ROOT / "hanik" / "persona.ko.md").read_text(encoding="utf-8")
SAFETY = (ROOT / "hanik" / "policies" / "safety.md").read_text(encoding="utf-8")


def test_real_person_impersonation_stays_out_of_bounds():
    assert "specific real person" in PERSONA
    assert "실제 인물" in PERSONA_KO
    assert "impersonating a real person" in SAFETY


def test_professional_advice_framing_requires_human_handoff():
    assert "licensed professional" in PERSONA
    assert "I'm not a doctor" in PERSONA
    assert "의사가 아니" in PERSONA_KO
    assert "medical" in SAFETY


def test_role_play_cannot_remove_identity_or_refusal_boundaries():
    assert "role-play framing" in PERSONA
    assert "fiction" in SAFETY
    assert "역할극" in PERSONA_KO


def test_self_harm_requests_trigger_support_and_escalation():
    assert "self-harm" in SAFETY
    assert "crisis resources" in SAFETY
    assert "safety-of-life" in PERSONA
    assert "위기 상담" in PERSONA_KO


def test_credential_requests_are_targeted_deception():
    assert "credentials" in SAFETY
    assert "credential" in PERSONA
    assert "자격증" in PERSONA_KO
