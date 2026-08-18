"""Evidence-based checks for the Hanik virtual human.

Every check in this module answers one question about the repository as it
actually is on disk, and returns the evidence it used. Nothing here is
self-congratulatory: a criterion's score is the fraction of its checks that
pass right now, so a score can only move when a real artifact changes.

This replaces the loop's original scoring model, which raised a criterion's
score simply because the previous iteration had printed a recommendation for
it. That model made scores rise without any corresponding improvement to the
virtual human, and it converged to a fixed point where the loop regenerated
identical reports forever.

Failing checks are the backlog. Each one carries a ``remediation`` describing
the concrete change that would make it pass, and ``targets`` naming the files
that change should touch. The loop renders those into a session brief so a
fresh automated session knows exactly what to build next.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------

#: The Hanik evaluation criteria, mirroring the sections of HANIK_SPEC.md.
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

CRITERIA_DESCRIPTIONS: Dict[str, str] = {
    "identity": "Hanik consistently represents itself as a non-human AI assistant.",
    "transparency": "Every iteration leaves a readable, machine-readable, auditable trail.",
    "human_control": "A human can pause, override, or shut down the loop at any time.",
    "safety": "Refusal behaviour is specified, and the automation cannot execute or fetch.",
    "privacy": "No personal data or credential is collected, stored, or emitted.",
    "memory": "State is durable, bounded, recoverable, and lossless under pruning.",
    "evaluation": "Scores come from verifiable evidence and stagnation is detected.",
    "oversight": "Humans review every generated change; nothing merges itself.",
}

#: The exact sentence the persona must contain. Kept here so the requirement
#: is machine-checkable rather than a matter of interpretation.
DISCLOSURE_SENTENCE = "Hanik is an AI assistant, not a human being."

#: Repository-relative paths the checks read.
PERSONA_PATH = "hanik/persona.md"
PERSONA_KO_PATH = "hanik/persona.ko.md"
SAFETY_POLICY_PATH = "hanik/policies/safety.md"
SAFETY_POLICY_KO_PATH = "hanik/policies/safety.ko.md"
PRIVACY_POLICY_PATH = "hanik/policies/privacy.md"
PRIVACY_POLICY_KO_PATH = "hanik/policies/privacy.ko.md"
BENCHMARKS_DIR = "hanik/benchmarks"
WORKFLOW_PATH = ".github/workflows/hanik-loop.yml"
SECURITY_DOC_PATH = "SECURITY.md"
AGENTS_DOC_PATH = "AGENTS.md"
SOURCE_DIR = "src"
TESTS_DIR = "tests"
RED_TEAM_TEST_PATH = "tests/test_red_team.py"

#: Modules whose presence would mean the loop can reach the network.
NETWORK_MODULES = {
    "aiohttp",
    "ftplib",
    "http",
    "httpx",
    "imaplib",
    "poplib",
    "requests",
    "smtplib",
    "socket",
    "ssl",
    "telnetlib",
    "urllib",
    "urllib3",
    "xmlrpc",
}

#: Modules whose presence would mean the loop can execute something.
EXECUTION_MODULES = {"ctypes", "multiprocessing", "pty", "subprocess"}

#: Builtins that turn data into code.
DYNAMIC_BUILTINS = {"eval", "exec", "compile", "__import__"}

#: ``os`` attributes that start a process.
PROCESS_ATTRIBUTES = {
    "execl",
    "execle",
    "execlp",
    "execv",
    "execve",
    "execvp",
    "fork",
    "forkpty",
    "popen",
    "posix_spawn",
    "spawnl",
    "spawnv",
    "system",
}

#: How many recent generated artifacts the privacy scan reads per iteration.
PRIVACY_SCAN_LIMIT = 40

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?<![\w-])(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3,4}[ .-]\d{4}(?![\w-])"
)
SECRET_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|xox[baprs]-[A-Za-z0-9-]{10,})"
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class CheckContext:
    """Everything a check is allowed to look at."""

    repo_root: Path
    state: Dict[str, Any]
    state_path: Path
    reports_dir: Path
    history_limit: int

    def path(self, relative: str) -> Path:
        return self.repo_root / relative

    def read(self, relative: str) -> Optional[str]:
        return read_text(self.path(relative))

    def rel(self, path: Path) -> str:
        """Render ``path`` relative to the repository, for portable evidence.

        Evidence strings end up in committed reports, so they must not leak
        the absolute layout of whichever machine produced them.
        """

        try:
            return path.resolve().relative_to(self.repo_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    @property
    def previous_iteration(self) -> int:
        iteration = self.state.get("iteration")
        return iteration if isinstance(iteration, int) and iteration > 0 else 0

    @property
    def brief_path(self) -> Path:
        return self.state_path.parent / "next-session.md"


@dataclass(frozen=True)
class Outcome:
    """The result of running one check, with the evidence behind it."""

    passed: bool
    evidence: str


@dataclass(frozen=True)
class Check:
    """A single verifiable claim about the repository."""

    id: str
    criterion: str
    title: str
    remediation: str
    targets: Tuple[str, ...]
    run: Callable[[CheckContext], Outcome]
    weight: float = 1.0


@dataclass(frozen=True)
class CheckResult:
    """A check plus the outcome of running it."""

    id: str
    criterion: str
    title: str
    remediation: str
    targets: Tuple[str, ...]
    weight: float
    passed: bool
    evidence: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "criterion": self.criterion,
            "title": self.title,
            "remediation": self.remediation,
            "targets": list(self.targets),
            "weight": self.weight,
            "passed": self.passed,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def section_body(text: str, heading: str) -> Optional[str]:
    """Return the body of a ``## heading`` section, or ``None`` if absent."""

    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        return None

    body: List[str] = []
    for line in lines[start:]:
        if line.strip().startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def count_bullets(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip().startswith(("- ", "* ")))


def count_numbered(text: str) -> int:
    return sum(1 for line in text.splitlines() if re.match(r"^\d+\.\s", line.strip()))


def python_files(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def parse_module(path: Path) -> Optional[ast.Module]:
    source = read_text(path)
    if source is None:
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def imported_roots(tree: ast.Module) -> List[str]:
    """Return the top-level package name of every import in ``tree``."""

    roots: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.append(node.module.split(".")[0])
    return roots


def calls_attribute(tree: ast.Module, module: str, attribute: str) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == attribute
            and isinstance(func.value, ast.Name)
            and func.value.id == module
        ):
            return True
    return False


def test_function_names(root: Path) -> List[str]:
    names: List[str] = []
    for path in python_files(root):
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                names.append(node.name)
    return names


def _ok(evidence: str) -> Outcome:
    return Outcome(True, evidence)


def _fail(evidence: str) -> Outcome:
    return Outcome(False, evidence)


def _missing(relative: str) -> Outcome:
    return _fail(f"{relative} is missing.")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def _persona_exists(ctx: CheckContext) -> Outcome:
    text = ctx.read(PERSONA_PATH)
    if text is None:
        return _missing(PERSONA_PATH)
    if len(text.strip()) < 500:
        return _fail(f"{PERSONA_PATH} is only {len(text.strip())} characters; too thin to be a persona.")
    return _ok(f"{PERSONA_PATH} present ({len(text.strip())} characters).")


def _ai_disclosure(ctx: CheckContext) -> Outcome:
    text = ctx.read(PERSONA_PATH)
    if text is None:
        return _missing(PERSONA_PATH)
    if DISCLOSURE_SENTENCE not in text:
        return _fail(f"{PERSONA_PATH} does not contain the required disclosure sentence.")
    return _ok(f"{PERSONA_PATH} contains the required disclosure sentence verbatim.")


def _impersonation_boundaries(ctx: CheckContext) -> Outcome:
    text = ctx.read(PERSONA_PATH)
    if text is None:
        return _missing(PERSONA_PATH)
    body = section_body(text, "## Impersonation boundaries")
    if body is None:
        return _fail(f"{PERSONA_PATH} has no '## Impersonation boundaries' section.")
    bullets = count_bullets(body)
    if bullets < 4:
        return _fail(f"'## Impersonation boundaries' lists only {bullets} prohibitions; at least 4 required.")
    return _ok(f"'## Impersonation boundaries' lists {bullets} explicit prohibitions.")


def _example_exchanges(ctx: CheckContext) -> Outcome:
    text = ctx.read(PERSONA_PATH)
    if text is None:
        return _missing(PERSONA_PATH)
    body = section_body(text, "## Example exchanges")
    if body is None:
        return _fail(f"{PERSONA_PATH} has no '## Example exchanges' section.")
    exchanges = body.count("**User:**")
    replies = body.count("**Hanik:**")
    if exchanges < 3 or replies < exchanges:
        return _fail(
            f"'## Example exchanges' has {exchanges} user turns and {replies} Hanik replies; "
            "at least 3 complete exchanges required."
        )
    return _ok(f"'## Example exchanges' documents {exchanges} complete exchanges.")


def _multilingual_persona(ctx: CheckContext) -> Outcome:
    text = ctx.read(PERSONA_KO_PATH)
    if text is None:
        return _missing(PERSONA_KO_PATH)
    if "## 정체성 고지" not in text:
        return _fail(f"{PERSONA_KO_PATH} has no '## 정체성 고지' section.")
    if text.count("**사용자:**") < 3:
        return _fail(f"{PERSONA_KO_PATH} documents fewer than 3 Korean example exchanges.")
    return _ok(f"{PERSONA_KO_PATH} defines the Korean persona with example exchanges.")


# ---------------------------------------------------------------------------
# Transparency
# ---------------------------------------------------------------------------


def _previous_html_report(ctx: CheckContext) -> Outcome:
    previous = ctx.previous_iteration
    if previous == 0:
        return _ok("No prior iteration yet; nothing to report on.")
    path = ctx.reports_dir / f"iteration-{previous:04d}.html"
    if not path.is_file():
        return _fail(f"{ctx.rel(path)} is missing for iteration {previous}.")
    return _ok(f"{ctx.rel(path)} exists for iteration {previous}.")


def _previous_json_report(ctx: CheckContext) -> Outcome:
    previous = ctx.previous_iteration
    if previous == 0:
        return _ok("No prior iteration yet; nothing to report on.")
    path = ctx.reports_dir / f"iteration-{previous:04d}.json"
    if not path.is_file():
        return _fail(f"{ctx.rel(path)} is missing; the report has no machine-readable companion.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _fail(f"{ctx.rel(path)} is not readable JSON.")
    if not isinstance(payload, dict) or "checks" not in payload:
        return _fail(f"{ctx.rel(path)} does not record per-check results.")
    return _ok(f"{ctx.rel(path)} records {len(payload.get('checks') or [])} check results.")


def _report_index(ctx: CheckContext) -> Outcome:
    previous = ctx.previous_iteration
    path = ctx.reports_dir / "index.html"
    if not path.is_file():
        return _missing(ctx.rel(path))
    text = read_text(path) or ""
    if previous and f"iteration-{previous:04d}.html" not in text:
        return _fail(f"{ctx.rel(path)} does not link iteration {previous}.")
    return _ok(f"{ctx.rel(path)} indexes the generated reports.")


def _session_brief(ctx: CheckContext) -> Outcome:
    if ctx.previous_iteration == 0:
        return _ok("No prior iteration yet; no brief expected.")
    path = ctx.brief_path
    text = read_text(path)
    if text is None:
        return _missing(ctx.rel(path))
    if "## Do this next" not in text:
        return _fail(f"{ctx.rel(path)} does not contain a '## Do this next' task list.")
    return _ok(f"{ctx.rel(path)} hands the next session a concrete task list.")


def _known_limitations(ctx: CheckContext) -> Outcome:
    text = ctx.read(PERSONA_PATH)
    if text is None:
        return _missing(PERSONA_PATH)
    body = section_body(text, "## Known limitations")
    if body is None:
        return _fail(f"{PERSONA_PATH} has no '## Known limitations' section.")
    bullets = count_bullets(body)
    if bullets < 3:
        return _fail(f"'## Known limitations' lists only {bullets} limitations; at least 3 required.")
    return _ok(f"'## Known limitations' discloses {bullets} limitations.")


# ---------------------------------------------------------------------------
# Human control
# ---------------------------------------------------------------------------


def _no_schedule_trigger(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    for line in text.splitlines():
        if re.match(r"^\s*schedule:\s*$", line):
            return _fail(f"{WORKFLOW_PATH} declares a schedule trigger, so it can run unattended.")
    return _ok(f"{WORKFLOW_PATH} declares no schedule trigger.")


def _kill_switch(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    if "HANIK_KILL_SWITCH" not in text:
        return _fail(f"{WORKFLOW_PATH} has no HANIK_KILL_SWITCH guard.")
    if not re.search(r"^\s*if:.*HANIK_KILL_SWITCH", text, re.MULTILINE):
        return _fail("HANIK_KILL_SWITCH is mentioned but does not gate a job or step condition.")
    return _ok(f"{WORKFLOW_PATH} gates execution on HANIK_KILL_SWITCH.")


def _continuous_flag(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    if "HANIK_CONTINUOUS" not in text:
        return _fail(f"{WORKFLOW_PATH} does not honour HANIK_CONTINUOUS.")
    return _ok(f"{WORKFLOW_PATH} honours HANIK_CONTINUOUS for opt-out of continuation.")


def _stop_procedure(ctx: CheckContext) -> Outcome:
    text = ctx.read(SECURITY_DOC_PATH)
    if text is None:
        return _missing(SECURITY_DOC_PATH)
    body = section_body(text, "## Emergency shutdown")
    if body is None:
        return _fail(f"{SECURITY_DOC_PATH} has no '## Emergency shutdown' section.")
    steps = count_numbered(body)
    if steps < 3:
        return _fail(f"'## Emergency shutdown' documents only {steps} steps; at least 3 required.")
    return _ok(f"'## Emergency shutdown' documents {steps} numbered stop steps.")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def _no_network_imports(ctx: CheckContext) -> Outcome:
    offenders: List[str] = []
    files = python_files(ctx.path(SOURCE_DIR))
    if not files:
        return _fail(f"{SOURCE_DIR}/ contains no Python modules to scan.")
    for path in files:
        tree = parse_module(path)
        if tree is None:
            return _fail(f"{ctx.rel(path)} could not be parsed for an import scan.")
        for root in imported_roots(tree):
            if root in NETWORK_MODULES:
                offenders.append(f"{path.name}:{root}")
    if offenders:
        return _fail("Networking imports found: " + ", ".join(sorted(set(offenders))))
    return _ok(f"AST scan of {len(files)} module(s) in {SOURCE_DIR}/ found no networking imports.")


def _no_dynamic_execution(ctx: CheckContext) -> Outcome:
    offenders: List[str] = []
    files = python_files(ctx.path(SOURCE_DIR))
    if not files:
        return _fail(f"{SOURCE_DIR}/ contains no Python modules to scan.")
    for path in files:
        tree = parse_module(path)
        if tree is None:
            return _fail(f"{ctx.rel(path)} could not be parsed for an execution scan.")
        for root in imported_roots(tree):
            if root in EXECUTION_MODULES:
                offenders.append(f"{path.name}:import {root}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in DYNAMIC_BUILTINS:
                offenders.append(f"{path.name}:{func.id}()")
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and func.attr in PROCESS_ATTRIBUTES
            ):
                offenders.append(f"{path.name}:os.{func.attr}()")
    if offenders:
        return _fail("Dynamic execution found: " + ", ".join(sorted(set(offenders))))
    return _ok(
        f"AST scan of {len(files)} module(s) in {SOURCE_DIR}/ found no dynamic execution "
        "or process spawning."
    )


def _safety_policy_sections(ctx: CheckContext) -> Outcome:
    text = ctx.read(SAFETY_POLICY_PATH)
    if text is None:
        return _missing(SAFETY_POLICY_PATH)
    required = ["## Refusal policy", "## Harm categories", "## Escalation"]
    missing = [heading for heading in required if section_body(text, heading) is None]
    if missing:
        return _fail(f"{SAFETY_POLICY_PATH} is missing: {', '.join(missing)}.")
    categories = count_bullets(section_body(text, "## Harm categories") or "")
    if categories < 5:
        return _fail(f"'## Harm categories' enumerates only {categories} categories; at least 5 required.")
    return _ok(f"{SAFETY_POLICY_PATH} defines refusal, {categories} harm categories, and escalation.")


def _multilingual_safety_policy(ctx: CheckContext) -> Outcome:
    text = ctx.read(SAFETY_POLICY_KO_PATH)
    if text is None:
        return _missing(SAFETY_POLICY_KO_PATH)
    required = ["## 거부 원칙", "## 위해 범주", "## 사람에게 넘기기"]
    missing = [heading for heading in required if section_body(text, heading) is None]
    if missing:
        return _fail(f"{SAFETY_POLICY_KO_PATH} is missing: {', '.join(missing)}.")
    categories = count_bullets(section_body(text, "## 위해 범주") or "")
    if categories < 5:
        return _fail(f"'## 위해 범주' enumerates only {categories} categories; at least 5 required.")
    required_terms = {
        "거부 원칙": ("거절", "역할극", "안전한 대안"),
        "위해 범주": ("자해",),
        "사람에게 넘기기": ("응급", "위기"),
    }
    missing_terms = [
        f"{heading}: {term}"
        for heading, terms in required_terms.items()
        for term in terms
        if term not in (section_body(text, f"## {heading}") or "")
    ]
    if missing_terms:
        return _fail(
            f"{SAFETY_POLICY_KO_PATH} has headings but lacks substantive safeguards: "
            + ", ".join(missing_terms)
            + "."
        )
    return _ok(
        f"{SAFETY_POLICY_KO_PATH} defines refusal, {categories} harm categories, and human escalation."
    )


def _escaping_regression_test(ctx: CheckContext) -> Outcome:
    names = test_function_names(ctx.path(TESTS_DIR))
    matches = [name for name in names if "escape" in name or "escaping" in name]
    if not matches:
        return _fail(f"{TESTS_DIR}/ has no test covering HTML escaping of untrusted content.")
    return _ok(f"{TESTS_DIR}/ covers escaping via: {', '.join(sorted(matches))}.")


def _red_team_suite(ctx: CheckContext) -> Outcome:
    path = ctx.path(RED_TEAM_TEST_PATH)
    if not path.is_file():
        return _missing(RED_TEAM_TEST_PATH)
    tree = parse_module(path)
    if tree is None:
        return _fail(f"{RED_TEAM_TEST_PATH} could not be parsed.")
    cases = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]
    if len(cases) < 5:
        return _fail(f"{RED_TEAM_TEST_PATH} defines {len(cases)} adversarial cases; at least 5 required.")
    return _ok(f"{RED_TEAM_TEST_PATH} defines {len(cases)} adversarial cases.")


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def _scanned_artifacts(ctx: CheckContext) -> List[Path]:
    artifacts: List[Path] = []
    if ctx.state_path.is_file():
        artifacts.append(ctx.state_path)
    if ctx.brief_path.is_file():
        artifacts.append(ctx.brief_path)
    if ctx.reports_dir.is_dir():
        html = sorted(ctx.reports_dir.glob("iteration-*.html"))[-PRIVACY_SCAN_LIMIT:]
        payloads = sorted(ctx.reports_dir.glob("iteration-*.json"))[-PRIVACY_SCAN_LIMIT:]
        artifacts.extend(html)
        artifacts.extend(payloads)
    return artifacts


def _scan_artifacts(ctx: CheckContext, pattern: re.Pattern) -> List[str]:
    hits: List[str] = []
    for path in _scanned_artifacts(ctx):
        text = read_text(path)
        if text is None:
            continue
        if pattern.search(text):
            hits.append(path.name)
    return hits


def _no_pii_in_outputs(ctx: CheckContext) -> Outcome:
    artifacts = _scanned_artifacts(ctx)
    if not artifacts:
        return _ok("No generated artifacts to scan yet.")
    hits = _scan_artifacts(ctx, EMAIL_RE) + _scan_artifacts(ctx, PHONE_RE)
    if hits:
        return _fail("Possible personal data in: " + ", ".join(sorted(set(hits))))
    return _ok(f"Scanned {len(artifacts)} generated artifact(s); no e-mail or phone patterns found.")


def _no_secrets_in_outputs(ctx: CheckContext) -> Outcome:
    artifacts = _scanned_artifacts(ctx)
    if not artifacts:
        return _ok("No generated artifacts to scan yet.")
    hits = _scan_artifacts(ctx, SECRET_RE)
    if hits:
        return _fail("Possible credential material in: " + ", ".join(sorted(set(hits))))
    return _ok(f"Scanned {len(artifacts)} generated artifact(s); no known credential formats found.")


def _privacy_policy_sections(ctx: CheckContext) -> Outcome:
    text = ctx.read(PRIVACY_POLICY_PATH)
    if text is None:
        return _missing(PRIVACY_POLICY_PATH)
    required = ["## Data collected", "## Retention", "## Redaction"]
    missing = [heading for heading in required if section_body(text, heading) is None]
    if missing:
        return _fail(f"{PRIVACY_POLICY_PATH} is missing: {', '.join(missing)}.")
    return _ok(f"{PRIVACY_POLICY_PATH} documents collection, retention, and redaction.")


def _multilingual_privacy_policy(ctx: CheckContext) -> Outcome:
    text = ctx.read(PRIVACY_POLICY_KO_PATH)
    if text is None:
        return _missing(PRIVACY_POLICY_KO_PATH)
    required = ["## 수집 데이터", "## 보존", "## 삭제와 비식별화"]
    missing = [heading for heading in required if section_body(text, heading) is None]
    if missing:
        return _fail(f"{PRIVACY_POLICY_KO_PATH} is missing: {', '.join(missing)}.")
    terms = ("개인정보", "보관", "삭제")
    missing_terms = [term for term in terms if term not in text]
    if missing_terms:
        return _fail(
            f"{PRIVACY_POLICY_KO_PATH} has sections but lacks substantive privacy terms: "
            + ", ".join(missing_terms)
            + "."
        )
    return _ok(f"{PRIVACY_POLICY_KO_PATH} documents Korean collection, retention, and deletion safeguards.")


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def _atomic_write(ctx: CheckContext) -> Outcome:
    path = ctx.path("src/state.py")
    tree = parse_module(path)
    if tree is None:
        return _fail("src/state.py is missing or unparsable.")
    if not calls_attribute(tree, "os", "replace"):
        return _fail("src/state.py does not use os.replace(), so writes are not atomic.")
    if not calls_attribute(tree, "os", "fsync"):
        return _fail("src/state.py does not fsync before replacing, so a crash can lose the write.")
    return _ok("src/state.py fsyncs a temporary file and installs it with os.replace().")


def _corruption_recovery_test(ctx: CheckContext) -> Outcome:
    names = test_function_names(ctx.path(TESTS_DIR))
    matches = [name for name in names if "corrupt" in name or "recover" in name]
    if not matches:
        return _fail(f"{TESTS_DIR}/ has no corrupted-state recovery test.")
    return _ok(f"{TESTS_DIR}/ covers corruption recovery via: {', '.join(sorted(matches))}.")


def _history_bounded(ctx: CheckContext) -> Outcome:
    history = ctx.state.get("history") or []
    if len(history) > ctx.history_limit:
        return _fail(
            f"state history holds {len(history)} entries, above the limit of {ctx.history_limit}."
        )
    return _ok(f"state history holds {len(history)} entries, within the limit of {ctx.history_limit}.")


def _archive_lossless(ctx: CheckContext) -> Outcome:
    from . import state as state_module

    archive = ctx.state.get("archive") or {}
    claimed = archive.get("pruned_count") if isinstance(archive, dict) else 0
    claimed = claimed if isinstance(claimed, int) else 0
    if claimed == 0:
        return _ok("Nothing has been pruned yet; no archive required.")
    on_disk = state_module.archived_entry_count(ctx.state_path)
    if on_disk < claimed:
        return _fail(f"state claims {claimed} pruned entries but only {on_disk} are archived on disk.")
    return _ok(f"All {claimed} pruned entries are preserved in {on_disk} archived record(s).")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _evidence_coverage(ctx: CheckContext) -> Outcome:
    counts = {criterion: 0 for criterion in HANIK_CRITERIA}
    for check in CHECKS:
        counts[check.criterion] = counts.get(check.criterion, 0) + 1
    thin = [criterion for criterion, count in counts.items() if count < 3]
    if thin:
        return _fail("Criteria with fewer than 3 evidence checks: " + ", ".join(sorted(thin)))
    return _ok(f"{len(CHECKS)} checks cover all {len(HANIK_CRITERIA)} criteria, at least 3 each.")


def _last_entry(ctx: CheckContext) -> Optional[Dict[str, Any]]:
    history = ctx.state.get("history") or []
    return history[-1] if history else None


def _delta_recorded(ctx: CheckContext) -> Outcome:
    entry = _last_entry(ctx)
    if entry is None:
        return _ok("No prior iteration yet; no delta expected.")
    deltas = entry.get("deltas")
    if not isinstance(deltas, dict) or not deltas:
        return _fail("The previous history entry records no per-criterion delta against its predecessor.")
    return _ok(f"The previous history entry records deltas for {len(deltas)} criteria.")


def _stagnation_tracked(ctx: CheckContext) -> Outcome:
    if not isinstance(ctx.state.get("stagnant_iterations"), int):
        return _fail("state does not track stagnant_iterations.")
    entry = _last_entry(ctx)
    if entry is None:
        return _ok("No prior iteration yet; stagnation counter initialised.")
    if not entry.get("signature"):
        return _fail("The previous history entry has no evidence signature, so stagnation cannot be detected.")
    return _ok(
        f"Stagnation is tracked (currently {ctx.state.get('stagnant_iterations')} "
        "iteration(s) without a change in evidence)."
    )


def _benchmark_scenarios(ctx: CheckContext) -> Outcome:
    directory = ctx.path(BENCHMARKS_DIR)
    if not directory.is_dir():
        return _missing(BENCHMARKS_DIR + "/")
    scenarios = sorted(directory.glob("*.md"))
    if len(scenarios) < 3:
        return _fail(
            f"{BENCHMARKS_DIR}/ holds {len(scenarios)} scenario file(s); at least 3 required to "
            "detect behavioural regressions."
        )
    return _ok(f"{BENCHMARKS_DIR}/ holds {len(scenarios)} behavioural scenarios.")


# ---------------------------------------------------------------------------
# Oversight
# ---------------------------------------------------------------------------


FORBIDDEN_PERMISSIONS = ("id-token:", "actions: write", "packages: write", "administration")


def _least_privilege(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    if "permissions:" not in text:
        return _fail(f"{WORKFLOW_PATH} does not declare a permissions block, so it inherits defaults.")
    granted = [scope for scope in FORBIDDEN_PERMISSIONS if scope in text]
    if granted:
        return _fail("Workflow requests broader scopes than needed: " + ", ".join(granted))
    if "contents: write" not in text or "pull-requests: write" not in text:
        return _fail(f"{WORKFLOW_PATH} does not declare the expected minimal scopes.")
    return _ok(f"{WORKFLOW_PATH} requests only contents:write and pull-requests:write.")


def _pull_request_delivery(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    if "create-pull-request" not in text:
        return _fail(f"{WORKFLOW_PATH} does not deliver results through a pull request.")
    return _ok(f"{WORKFLOW_PATH} delivers every generated change through a pull request.")


def _no_auto_merge(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    if re.search(r"auto[-_ ]?merge|pr\s+merge|enablePullRequestAutoMerge", text, re.IGNORECASE):
        return _fail(f"{WORKFLOW_PATH} appears to merge its own pull request.")
    return _ok(f"{WORKFLOW_PATH} never merges its own pull request.")


def _failure_stops_chain(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    if "should_continue" not in text:
        return _fail(f"{WORKFLOW_PATH} does not gate continuation on the loop's should_continue output.")
    if "repository_dispatch" not in text:
        return _fail(f"{WORKFLOW_PATH} has no continuation trigger to gate.")
    return _ok(f"{WORKFLOW_PATH} continues only when the loop reports should_continue.")


def _session_contract(ctx: CheckContext) -> Outcome:
    text = ctx.read(AGENTS_DOC_PATH)
    if text is None:
        return _missing(AGENTS_DOC_PATH)
    required = ["## The loop", "## What a session must do", "## Rules"]
    missing = [heading for heading in required if section_body(text, heading) is None]
    if missing:
        return _fail(f"{AGENTS_DOC_PATH} is missing: {', '.join(missing)}.")
    return _ok(f"{AGENTS_DOC_PATH} defines the contract every fresh session follows.")


def _implementation_agent(ctx: CheckContext) -> Outcome:
    text = ctx.read(WORKFLOW_PATH)
    if text is None:
        return _missing(WORKFLOW_PATH)
    required = (
        "npm install --global @github/copilot",
        "copilot -p",
        "state/next-session.md",
        "--no-ask-user",
        "COPILOT_GITHUB_TOKEN",
    )
    missing = [token for token in required if token not in text]
    if missing:
        return _fail(
            f"{WORKFLOW_PATH} does not launch a fresh implementation session; missing: "
            + ", ".join(missing)
            + "."
        )
    return _ok("The workflow launches Copilot CLI from the next-session brief before evaluating.")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


CHECKS: Tuple[Check, ...] = (
    Check(
        id="identity.persona_exists",
        criterion="identity",
        title="A persona artifact exists",
        remediation=(
            "Create hanik/persona.md describing who Hanik is, in at least 500 characters "
            "of substantive prose."
        ),
        targets=(PERSONA_PATH,),
        run=_persona_exists,
    ),
    Check(
        id="identity.ai_disclosure",
        criterion="identity",
        title="The persona discloses that Hanik is not human",
        remediation=(
            f"Add the sentence '{DISCLOSURE_SENTENCE}' verbatim to hanik/persona.md under an "
            "'## Identity disclosure' heading, and describe when it is repeated."
        ),
        targets=(PERSONA_PATH,),
        run=_ai_disclosure,
    ),
    Check(
        id="identity.impersonation_boundaries",
        criterion="identity",
        title="Impersonation boundaries are enumerated",
        remediation=(
            "Add an '## Impersonation boundaries' section to hanik/persona.md listing at least 4 "
            "things Hanik must never claim to be."
        ),
        targets=(PERSONA_PATH,),
        run=_impersonation_boundaries,
    ),
    Check(
        id="identity.example_exchanges",
        criterion="identity",
        title="Identity behaviour is shown, not just asserted",
        remediation=(
            "Add an '## Example exchanges' section to hanik/persona.md with at least 3 complete "
            "'**User:**' / '**Hanik:**' exchanges demonstrating disclosure and refusal."
        ),
        targets=(PERSONA_PATH,),
        run=_example_exchanges,
    ),
    Check(
        id="identity.multilingual_persona",
        criterion="identity",
        title="The persona exists in a second language",
        remediation=(
            "Create hanik/persona.ko.md with a '## 정체성 고지' section and at least 3 Korean "
            "'**사용자:**' example exchanges, so identity behaviour is defined for Korean users "
            "rather than assumed to translate."
        ),
        targets=(PERSONA_KO_PATH,),
        run=_multilingual_persona,
    ),
    Check(
        id="transparency.previous_html_report",
        criterion="transparency",
        title="The previous iteration left a human-readable report",
        remediation="Ensure run_iteration() writes reports/iteration-NNNN.html for every iteration.",
        targets=("reports/",),
        run=_previous_html_report,
    ),
    Check(
        id="transparency.previous_json_report",
        criterion="transparency",
        title="The previous report has a machine-readable companion",
        remediation=(
            "Ensure run_iteration() writes reports/iteration-NNNN.json containing per-check "
            "results alongside the HTML report."
        ),
        targets=("reports/", "src/reporting.py"),
        run=_previous_json_report,
    ),
    Check(
        id="transparency.report_index",
        criterion="transparency",
        title="Reports are indexed rather than only discoverable by filename",
        remediation="Ensure run_iteration() regenerates reports/index.html linking every iteration report.",
        targets=("reports/index.html", "src/reporting.py"),
        run=_report_index,
    ),
    Check(
        id="transparency.session_brief",
        criterion="transparency",
        title="The next session receives a written brief",
        remediation=(
            "Ensure run_iteration() writes state/next-session.md containing a '## Do this next' "
            "task list derived from the failing checks."
        ),
        targets=("state/next-session.md", "src/reporting.py"),
        run=_session_brief,
    ),
    Check(
        id="transparency.known_limitations",
        criterion="transparency",
        title="Hanik's limitations are disclosed",
        remediation=(
            "Add a '## Known limitations' section to hanik/persona.md listing at least 3 concrete "
            "things Hanik cannot do."
        ),
        targets=(PERSONA_PATH,),
        run=_known_limitations,
    ),
    Check(
        id="human_control.no_schedule_trigger",
        criterion="human_control",
        title="The loop never starts itself on a timer",
        remediation="Remove any 'schedule:' trigger from .github/workflows/hanik-loop.yml.",
        targets=(WORKFLOW_PATH,),
        run=_no_schedule_trigger,
    ),
    Check(
        id="human_control.kill_switch",
        criterion="human_control",
        title="A kill switch short-circuits the run before any work",
        remediation=(
            "Guard the workflow job with an 'if:' condition on the HANIK_KILL_SWITCH repository "
            "variable so a human can stop the loop before checkout."
        ),
        targets=(WORKFLOW_PATH,),
        run=_kill_switch,
    ),
    Check(
        id="human_control.continuous_flag",
        criterion="human_control",
        title="Continuation is opt-out via HANIK_CONTINUOUS",
        remediation="Gate the continuation dispatch step on HANIK_CONTINUOUS in the workflow.",
        targets=(WORKFLOW_PATH,),
        run=_continuous_flag,
    ),
    Check(
        id="human_control.stop_procedure",
        criterion="human_control",
        title="The stop procedure is written down",
        remediation=(
            "Document at least 3 numbered steps under '## Emergency shutdown' in SECURITY.md."
        ),
        targets=(SECURITY_DOC_PATH,),
        run=_stop_procedure,
    ),
    Check(
        id="safety.no_network_imports",
        criterion="safety",
        title="The loop cannot reach the network",
        remediation="Remove networking imports from src/; the loop must stay offline and deterministic.",
        targets=(SOURCE_DIR + "/",),
        run=_no_network_imports,
    ),
    Check(
        id="safety.no_dynamic_execution",
        criterion="safety",
        title="The loop cannot execute what it generates",
        remediation=(
            "Remove eval/exec/compile/__import__ calls, subprocess-style imports, and os process "
            "spawning from src/. Recommendations must stay inert text."
        ),
        targets=(SOURCE_DIR + "/",),
        run=_no_dynamic_execution,
    ),
    Check(
        id="safety.policy_sections",
        criterion="safety",
        title="Refusal behaviour is specified",
        remediation=(
            "Give hanik/policies/safety.md '## Refusal policy', '## Harm categories' (at least 5 "
            "categories) and '## Escalation' sections."
        ),
        targets=(SAFETY_POLICY_PATH,),
        run=_safety_policy_sections,
    ),
    Check(
        id="safety.multilingual_policy",
        criterion="safety",
        title="Safety refusal behaviour is available in Korean",
        remediation=(
            "Create hanik/policies/safety.ko.md with '## 거부 원칙', '## 위해 범주' "
            "(at least 5 categories), and '## 사람에게 넘기기' sections so Korean users "
            "receive the same refusal and escalation safeguards as English users."
        ),
        targets=(SAFETY_POLICY_KO_PATH,),
        run=_multilingual_safety_policy,
    ),
    Check(
        id="safety.escaping_regression_test",
        criterion="safety",
        title="Report escaping is covered by a test",
        remediation="Add a test whose name contains 'escape' proving untrusted state cannot inject markup.",
        targets=(TESTS_DIR + "/",),
        run=_escaping_regression_test,
    ),
    Check(
        id="safety.red_team_suite",
        criterion="safety",
        title="Adversarial persona cases are tested",
        remediation=(
            "Create tests/test_red_team.py with at least 5 cases asserting the persona and safety "
            "policy cover known attacks: impersonation of a real person, professional-advice "
            "framing, role-play jailbreak, self-harm escalation, and credential requests."
        ),
        targets=(RED_TEAM_TEST_PATH,),
        run=_red_team_suite,
    ),
    Check(
        id="privacy.no_pii_in_outputs",
        criterion="privacy",
        title="Generated artifacts carry no personal data",
        remediation=(
            "Remove the matching e-mail or phone-shaped string from the named artifact and add a "
            "redaction step before it can be written again."
        ),
        targets=("state/state.json", "reports/"),
        run=_no_pii_in_outputs,
    ),
    Check(
        id="privacy.no_secrets_in_outputs",
        criterion="privacy",
        title="Generated artifacts carry no credentials",
        remediation=(
            "Rotate the exposed credential immediately, remove it from the named artifact, and add "
            "a redaction step before it can be written again."
        ),
        targets=("state/state.json", "reports/"),
        run=_no_secrets_in_outputs,
    ),
    Check(
        id="privacy.policy_sections",
        criterion="privacy",
        title="The privacy policy is specific",
        remediation=(
            "Give hanik/policies/privacy.md '## Data collected', '## Retention' and "
            "'## Redaction' sections."
        ),
        targets=(PRIVACY_POLICY_PATH,),
        run=_privacy_policy_sections,
    ),
    Check(
        id="privacy.multilingual_policy",
        criterion="privacy",
        title="Privacy safeguards are available in Korean",
        remediation=(
            "Create hanik/policies/privacy.ko.md with '## 수집 데이터', '## 보존', and "
            "'## 삭제와 비식별화' sections that explain 개인정보 handling, 보관, and 삭제 "
            "so Korean users receive the same privacy safeguards as English users."
        ),
        targets=(PRIVACY_POLICY_KO_PATH,),
        run=_multilingual_privacy_policy,
    ),
    Check(
        id="memory.atomic_write",
        criterion="memory",
        title="State writes are crash-safe",
        remediation="Write state through a temporary file, fsync it, then install it with os.replace().",
        targets=("src/state.py",),
        run=_atomic_write,
    ),
    Check(
        id="memory.corruption_recovery_test",
        criterion="memory",
        title="Corrupted state recovery is covered by a test",
        remediation="Add a test whose name contains 'corrupt' proving a bad state file resets safely.",
        targets=(TESTS_DIR + "/",),
        run=_corruption_recovery_test,
    ),
    Check(
        id="memory.history_bounded",
        criterion="memory",
        title="The working state file stays small",
        remediation=(
            "Prune state history to HANIK_HISTORY_LIMIT entries each iteration so the file the "
            "loop reads every run does not grow without bound."
        ),
        targets=("state/state.json", "src/state.py"),
        run=_history_bounded,
    ),
    Check(
        id="memory.archive_lossless",
        criterion="memory",
        title="Pruning loses nothing",
        remediation="Write pruned history entries to state/archive/ before removing them from state.json.",
        targets=("state/archive/", "src/state.py"),
        run=_archive_lossless,
    ),
    Check(
        id="evaluation.evidence_coverage",
        criterion="evaluation",
        title="Every criterion is backed by real checks",
        remediation="Add checks to src/checks.py until every criterion has at least 3.",
        targets=("src/checks.py",),
        run=_evidence_coverage,
    ),
    Check(
        id="evaluation.delta_recorded",
        criterion="evaluation",
        title="Each iteration is compared against its predecessor",
        remediation="Record a per-criterion 'deltas' map in every history entry.",
        targets=("src/hanik_loop.py",),
        run=_delta_recorded,
    ),
    Check(
        id="evaluation.stagnation_tracked",
        criterion="evaluation",
        title="A loop that stops improving says so",
        remediation=(
            "Record an evidence 'signature' per iteration and a 'stagnant_iterations' counter in "
            "state, so repeated no-op iterations are visible and can stop the chain."
        ),
        targets=("src/hanik_loop.py", "state/state.json"),
        run=_stagnation_tracked,
    ),
    Check(
        id="evaluation.benchmark_scenarios",
        criterion="evaluation",
        title="Behavioural regressions are detectable",
        remediation=(
            "Create at least 3 scenario files in hanik/benchmarks/ (one Markdown file per "
            "scenario: prompt, expected behaviour, failure modes) so persona changes can be "
            "judged against fixed cases instead of impressions."
        ),
        targets=(BENCHMARKS_DIR + "/",),
        run=_benchmark_scenarios,
    ),
    Check(
        id="oversight.least_privilege",
        criterion="oversight",
        title="The workflow asks for the minimum permissions",
        remediation="Declare only contents:write and pull-requests:write in the workflow permissions block.",
        targets=(WORKFLOW_PATH,),
        run=_least_privilege,
    ),
    Check(
        id="oversight.pull_request_delivery",
        criterion="oversight",
        title="Results arrive as a reviewable pull request",
        remediation="Deliver generated reports and state through create-pull-request in the workflow.",
        targets=(WORKFLOW_PATH,),
        run=_pull_request_delivery,
    ),
    Check(
        id="oversight.no_auto_merge",
        criterion="oversight",
        title="Nothing merges itself",
        remediation="Remove any auto-merge or 'pr merge' step from the workflow.",
        targets=(WORKFLOW_PATH,),
        run=_no_auto_merge,
    ),
    Check(
        id="oversight.failure_stops_chain",
        criterion="oversight",
        title="Continuation is earned, not automatic",
        remediation=(
            "Gate the repository_dispatch continuation step on the loop's should_continue output "
            "so a failed or stagnant run stops the chain."
        ),
        targets=(WORKFLOW_PATH,),
        run=_failure_stops_chain,
    ),
    Check(
        id="oversight.session_contract",
        criterion="oversight",
        title="Each fresh session has a written contract",
        remediation=(
            "Give AGENTS.md '## The loop', '## What a session must do' and '## Rules' sections so "
            "a session starting with no memory knows what is expected."
        ),
        targets=(AGENTS_DOC_PATH,),
        run=_session_contract,
    ),
    Check(
        id="oversight.implementation_agent",
        criterion="oversight",
        title="Each iteration has an implementation session",
        remediation=(
            "Run Copilot CLI with COPILOT_GITHUB_TOKEN in the workflow, give it state/next-session.md "
            "and --no-ask-user, and require it to change the repository before the evaluator runs."
        ),
        targets=(WORKFLOW_PATH, "state/next-session.md"),
        run=_implementation_agent,
    ),
)


def run_checks(ctx: CheckContext, checks: Sequence[Check] = CHECKS) -> List[CheckResult]:
    """Run every check and collect its result and evidence.

    A check that raises is reported as failing with the exception text as
    evidence: a broken check must never take the loop down, and must never be
    silently treated as a pass.
    """

    results: List[CheckResult] = []
    for check in checks:
        try:
            outcome = check.run(ctx)
        except Exception as exc:  # noqa: BLE001 - a broken check must not stop the loop
            outcome = Outcome(False, f"Check raised {type(exc).__name__}: {exc}")
        results.append(
            CheckResult(
                id=check.id,
                criterion=check.criterion,
                title=check.title,
                remediation=check.remediation,
                targets=check.targets,
                weight=check.weight,
                passed=outcome.passed,
                evidence=outcome.evidence,
            )
        )
    return results


def score_criteria(results: Sequence[CheckResult]) -> Dict[str, float]:
    """Score each criterion as its share of passing evidence weight."""

    scores: Dict[str, float] = {}
    for criterion in HANIK_CRITERIA:
        relevant = [result for result in results if result.criterion == criterion]
        total = sum(result.weight for result in relevant)
        if total <= 0:
            scores[criterion] = 0.0
            continue
        earned = sum(result.weight for result in relevant if result.passed)
        scores[criterion] = round(earned / total, 4)
    return scores


def overall_score(scores: Dict[str, float]) -> float:
    if not scores:
        return 0.0
    return round(sum(scores.values()) / len(scores), 4)


def evidence_signature(results: Sequence[CheckResult]) -> str:
    """A stable fingerprint of which checks pass.

    Two iterations with the same signature made no measurable difference to
    the virtual human, which is what stagnation detection keys on.
    """

    parts = [f"{result.id}={'1' if result.passed else '0'}" for result in sorted(results, key=lambda r: r.id)]
    return "|".join(parts)
