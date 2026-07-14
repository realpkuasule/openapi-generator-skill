#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering"
SKILL_SCRIPTS = SKILL_ROOT / "scripts"
REPORT_SCHEMA = REPO_ROOT / "contracts" / "schemas" / "verification-report.schema.json"
DEFAULT_QUICK_VALIDATE = (
    Path.home()
    / ".codex"
    / "skills"
    / ".system"
    / "skill-creator"
    / "scripts"
    / "quick_validate.py"
)
PROTECTED_ROOTS = (REPO_ROOT / "contracts", SKILL_ROOT, REPO_ROOT / "scripts")
IGNORED_PARTS = {"__pycache__", ".DS_Store"}


@dataclass(frozen=True)
class Gate:
    name: str
    command: list[str]
    required_paths: list[Path] = field(default_factory=list)
    risk: str | None = None
    rollback: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_evidence(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return sha256_bytes(path.read_bytes())


def safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "gate"


def prepare_evidence_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for evidence_log in path.glob("*.log"):
        if evidence_log.is_file():
            evidence_log.unlink()


def source_digest() -> str:
    hasher = hashlib.sha256()
    for root in PROTECTED_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
                continue
            hasher.update(path.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(path.read_bytes())
            hasher.update(b"\0")
    return hasher.hexdigest()


def run_gate(gate: Gate, evidence_path: Path) -> dict[str, Any]:
    missing = [str(path) for path in gate.required_paths if not path.is_file()]
    if missing:
        content = "Required path is missing:\n" + "\n".join(missing) + "\n"
        digest = write_evidence(evidence_path, content)
        return {
            "name": gate.name,
            "command": gate.command,
            "exit_code": None,
            "status": "blocked",
            "duration_ms": 0,
            "evidence": str(evidence_path.resolve()),
            "evidence_sha256": digest,
            "risk": gate.risk or "A required verification capability is unavailable.",
            "rollback": gate.rollback,
        }

    started = time.monotonic()
    try:
        result = subprocess.run(
            gate.command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        digest = write_evidence(evidence_path, f"Unable to start command: {exc}\n")
        return {
            "name": gate.name,
            "command": gate.command,
            "exit_code": None,
            "status": "blocked",
            "duration_ms": duration_ms,
            "evidence": str(evidence_path.resolve()),
            "evidence_sha256": digest,
            "risk": gate.risk or "The verification command could not be started.",
            "rollback": gate.rollback,
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    content = (
        f"command={json.dumps(gate.command, ensure_ascii=False)}\n"
        f"exit_code={result.returncode}\n"
        "stdout:\n"
        f"{result.stdout}"
        "\nstderr:\n"
        f"{result.stderr}"
    )
    digest = write_evidence(evidence_path, content)
    return {
        "name": gate.name,
        "command": gate.command,
        "exit_code": result.returncode,
        "status": "passed" if result.returncode == 0 else "failed",
        "duration_ms": duration_ms,
        "evidence": str(evidence_path.resolve()),
        "evidence_sha256": digest,
        "risk": gate.risk if result.returncode else None,
        "rollback": gate.rollback,
    }


def internal_integrity_gate(before: str, evidence_path: Path) -> dict[str, Any]:
    after = source_digest()
    passed = before == after
    digest = write_evidence(
        evidence_path,
        json.dumps({"before": before, "after": after}, sort_keys=True) + "\n",
    )
    return {
        "name": "source-tree-read-only",
        "command": [
            "internal:sha256-tree",
            "contracts",
            "skills/openapi-engineering",
            "scripts",
        ],
        "exit_code": 0 if passed else 1,
        "status": "passed" if passed else "failed",
        "duration_ms": 0,
        "evidence": str(evidence_path.resolve()),
        "evidence_sha256": digest,
        "risk": None if passed else "A verification gate modified protected source files.",
        "rollback": None,
    }


def deterministic_gates() -> list[Gate]:
    python = sys.executable
    quick_validate = Path(
        os.environ.get("OPENAPI_ENGINEERING_QUICK_VALIDATE", DEFAULT_QUICK_VALIDATE)
    ).expanduser()
    return [
        Gate(
            "contract-validation",
            [python, "-m", "unittest", "tests.test_contracts", "tests.test_environment", "-v"],
        ),
        Gate(
            "captured-example-conformance",
            [python, str(REPO_ROOT / "scripts" / "capture_contract_examples.py"), "--check"],
        ),
        Gate(
            "unit-test-suite",
            [python, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
        Gate(
            "skill-quick-validation",
            [python, str(quick_validate), str(SKILL_ROOT)],
            required_paths=[quick_validate],
            risk="Skill packaging cannot be certified without the canonical validator.",
        ),
        Gate("inspect-project-help", [python, str(SKILL_SCRIPTS / "inspect_project.py"), "--help"]),
        Gate("validate-profile-help", [python, str(SKILL_SCRIPTS / "validate_profile.py"), "--help"]),
        Gate("compare-generation-help", [python, str(SKILL_SCRIPTS / "compare_generation.py"), "--help"]),
        Gate("profile-state-help", [python, str(SKILL_SCRIPTS / "profile_state.py"), "--help"]),
        Gate(
            "eval-case-validation",
            [python, str(REPO_ROOT / "scripts" / "evals" / "load_cases.py")],
        ),
        Gate(
            "eval-runner-help",
            [python, str(REPO_ROOT / "scripts" / "run_skill_evals.py"), "--help"],
        ),
        Gate(
            "eval-scorer-help",
            [python, str(REPO_ROOT / "scripts" / "evals" / "score_result.py"), "--help"],
        ),
        Gate(
            "skill-installer-dry-run",
            [
                python,
                str(REPO_ROOT / "scripts" / "install_skill.py"),
                "--home",
                "/tmp/openapi-engineering-installer-dry-run",
            ],
        ),
        Gate(
            "tdd-evidence-help",
            [python, str(REPO_ROOT / "scripts" / "tdd_evidence.py"), "--help"],
        ),
    ]


def aggregate_status(gates: Sequence[dict[str, Any]]) -> tuple[str, int]:
    statuses = {gate["status"] for gate in gates}
    if "blocked" in statuses or "unverified" in statuses:
        return "blocked", 2
    if "failed" in statuses:
        return "failed", 1
    return "passed", 0


def blocked_tier_gate(tier: str, evidence_path: Path) -> dict[str, Any]:
    content = (
        f"The {tier} tier requires real Codex/Claude adapter execution, which is outside "
        "the currently authorized deterministic checkpoint.\n"
    )
    digest = write_evidence(evidence_path, content)
    return {
        "name": f"{tier}-adapter-authorization",
        "command": ["authorization:codex-claude-forward-test"],
        "exit_code": None,
        "status": "blocked",
        "duration_ms": 0,
        "evidence": str(evidence_path.resolve()),
        "evidence_sha256": digest,
        "risk": "Forward testing could consume model quota or invoke external tools.",
        "rollback": None,
    }


def validate_report(report: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(report), key=lambda item: list(item.path))
    if errors:
        raise ValueError("Verification report does not satisfy its schema: " + errors[0].message)


def persist_report(report_path: Path, report: dict[str, Any]) -> None:
    validate_report(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def run_verification(
    tier: str,
    report_path: Path,
    *,
    gates: Sequence[Gate] | None = None,
) -> tuple[dict[str, Any], int]:
    report_path = report_path.expanduser().resolve()
    evidence_dir = report_path.parent / f"{report_path.stem}-evidence"
    prepare_evidence_dir(evidence_dir)
    started_at = utc_now()
    results: list[dict[str, Any]] = []

    if gates is None and tier != "deterministic":
        results.append(blocked_tier_gate(tier, evidence_dir / "01-adapter-authorization.log"))
    else:
        selected = list(gates) if gates is not None else deterministic_gates()
        before = source_digest()
        for index, gate in enumerate(selected, start=1):
            evidence_path = evidence_dir / f"{index:02d}-{safe_name(gate.name)}.log"
            results.append(run_gate(gate, evidence_path))
        results.append(
            internal_integrity_gate(
                before,
                evidence_dir / f"{len(results) + 1:02d}-source-tree-read-only.log",
            )
        )

    status, exit_code = aggregate_status(results)
    report = {
        "report_version": 1,
        "tier": tier,
        "status": status,
        "started_at": started_at,
        "finished_at": utc_now(),
        "gates": results,
    }
    persist_report(report_path, report)
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenAPI engineering verification gates.")
    parser.add_argument(
        "--tier",
        choices=("deterministic", "forward", "full"),
        default="deterministic",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Report path (default: docs/verifications/latest/<tier>-report.json).",
    )
    args = parser.parse_args()
    report_path = args.report or (
        REPO_ROOT / "docs" / "verifications" / "latest" / f"{args.tier}-report.json"
    )
    report, exit_code = run_verification(args.tier, report_path)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
