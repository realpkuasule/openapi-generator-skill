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
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering"
MAINTAINER_ROOT = REPO_ROOT / "skills" / "openapi-engineering-maintainer"
SKILL_SCRIPTS = SKILL_ROOT / "scripts"
REPORT_SCHEMA = REPO_ROOT / "contracts" / "schemas" / "verification-report.schema.json"
TRACEABILITY_MANIFEST = REPO_ROOT / "contracts" / "acceptance-traceability.yaml"
SELF_IMPROVEMENT_MANIFEST = (
    REPO_ROOT / "contracts" / "self-improvement-acceptance-traceability.yaml"
)
DEFAULT_QUICK_VALIDATE = (
    REPO_ROOT / "scripts" / "quick_validate.py"
)
PROTECTED_ROOTS = (
    REPO_ROOT / "bin",
    REPO_ROOT / "contracts",
    REPO_ROOT / "lib",
    REPO_ROOT / "packaging",
    REPO_ROOT / "scripts",
    REPO_ROOT / "skills",
)
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


def redact_machine_paths(value: str) -> str:
    replacements = (
        (str(REPO_ROOT.resolve()), "<repo>"),
        (str(Path.home().resolve()), "~"),
    )
    redacted = value
    for source, replacement in replacements:
        redacted = redacted.replace(source, replacement)
    return redacted


def portable_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def portable_command(command: Sequence[str]) -> list[str]:
    return [redact_machine_paths(str(argument)) for argument in command]


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
    display_command = portable_command(gate.command)
    missing = [portable_path(path) for path in gate.required_paths if not path.is_file()]
    if missing:
        content = "Required path is missing:\n" + "\n".join(missing) + "\n"
        digest = write_evidence(evidence_path, content)
        return {
            "name": gate.name,
            "command": display_command,
            "exit_code": None,
            "status": "blocked",
            "duration_ms": 0,
            "evidence": portable_path(evidence_path),
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
        digest = write_evidence(
            evidence_path,
            redact_machine_paths(f"Unable to start command: {exc}\n"),
        )
        return {
            "name": gate.name,
            "command": display_command,
            "exit_code": None,
            "status": "blocked",
            "duration_ms": duration_ms,
            "evidence": portable_path(evidence_path),
            "evidence_sha256": digest,
            "risk": gate.risk or "The verification command could not be started.",
            "rollback": gate.rollback,
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    content = redact_machine_paths(
        f"command={json.dumps(display_command, ensure_ascii=False)}\n"
        f"exit_code={result.returncode}\n"
        "stdout:\n"
        f"{result.stdout}"
        "\nstderr:\n"
        f"{result.stderr}"
    )
    digest = write_evidence(evidence_path, content)
    return {
        "name": gate.name,
        "command": display_command,
        "exit_code": result.returncode,
        "status": "passed" if result.returncode == 0 else "failed",
        "duration_ms": duration_ms,
        "evidence": portable_path(evidence_path),
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
        "evidence": portable_path(evidence_path),
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
        Gate(
            "maintainer-skill-quick-validation",
            [python, str(quick_validate), str(MAINTAINER_ROOT)],
            required_paths=[quick_validate, MAINTAINER_ROOT / "SKILL.md"],
            risk="Maintainer Skill packaging cannot be certified without the canonical validator.",
        ),
        Gate(
            "self-improvement-usage-e2e",
            [python, "-m", "unittest", "tests.test_self_improvement_e2e", "-v"],
        ),
        Gate(
            "self-improvement-traceability",
            [
                python,
                str(REPO_ROOT / "scripts" / "check_self_improvement_traceability.py"),
                "--manifest",
                str(SELF_IMPROVEMENT_MANIFEST),
                "--verify",
            ],
            required_paths=[
                REPO_ROOT / "scripts" / "check_self_improvement_traceability.py",
                SELF_IMPROVEMENT_MANIFEST,
            ],
        ),
        Gate(
            "usage-cli-help",
            ["node", str(REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"), "--help"],
            required_paths=[REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"],
            risk="The packaged Node usage runtime is unavailable.",
        ),
        Gate(
            "maintenance-analysis-help",
            [python, str(REPO_ROOT / "scripts" / "maintenance" / "analyze_usage.py"), "--help"],
        ),
        Gate(
            "maintenance-proposal-help",
            [python, str(REPO_ROOT / "scripts" / "maintenance" / "build_proposal.py"), "--help"],
        ),
        Gate(
            "maintenance-promotion-help",
            [python, str(REPO_ROOT / "scripts" / "maintenance" / "promote_candidate.py"), "--help"],
        ),
        Gate(
            "maintainer-eval-case-validation",
            [
                python,
                str(REPO_ROOT / "scripts" / "evals" / "load_cases.py"),
                "--root",
                str(MAINTAINER_ROOT / "evals"),
            ],
            required_paths=[MAINTAINER_ROOT / "evals" / "ordinary-handoff.yaml"],
        ),
        Gate(
            "npm-package-dry-run",
            ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
            required_paths=[REPO_ROOT / "package.json"],
            risk="The npm runtime allowlist could not be verified.",
        ),
        Gate(
            "inspect-project-help",
            [python, str(SKILL_SCRIPTS / "inspect_project.py"), "--help"],
        ),
        Gate(
            "validate-profile-help",
            [python, str(SKILL_SCRIPTS / "validate_profile.py"), "--help"],
        ),
        Gate(
            "compare-generation-help",
            [python, str(SKILL_SCRIPTS / "compare_generation.py"), "--help"],
        ),
        Gate(
            "empirical-gate-help",
            [python, str(SKILL_SCRIPTS / "run_empirical_gate.py"), "--help"],
        ),
        Gate(
            "scope-snapshot-help",
            [python, str(SKILL_SCRIPTS / "scope_snapshot.py"), "--help"],
        ),
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
            "forward-eval-aggregator-help",
            [python, str(REPO_ROOT / "scripts" / "aggregate_forward_evals.py"), "--help"],
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
    if tier == "forward":
        content = (
            "The forward tier requires a fresh combined Codex/Claude report. "
            "It never invokes either model platform implicitly.\n"
        )
        risk = "Missing forward evidence cannot be treated as a passing release gate."
        command = ["evidence:combined-forward-report"]
    else:
        content = (
            "The full tier requires fresh deterministic, forward, empirical, upgrade, "
            "and traceability release evidence. It checks existing evidence and never "
            "runs a generator or model platform implicitly.\n"
        )
        risk = "Missing release evidence cannot be treated as a passing release gate."
        command = ["evidence:complete-release-candidate"]
    digest = write_evidence(evidence_path, content)
    return {
        "name": f"{tier}-prerequisite",
        "command": command,
        "exit_code": None,
        "status": "blocked",
        "duration_ms": 0,
        "evidence": portable_path(evidence_path),
        "evidence_sha256": digest,
        "risk": risk,
        "rollback": None,
    }


def forward_gates(forward_report: Path) -> list[Gate]:
    aggregator = REPO_ROOT / "scripts" / "aggregate_forward_evals.py"
    return [
        Gate(
            "combined-forward-report",
            [sys.executable, str(aggregator), "--check-report", str(forward_report)],
            required_paths=[aggregator, forward_report],
            risk="The combined forward report is missing, invalid, stale, or failed.",
        )
    ]


def full_evidence_gates(
    *,
    forward_report: Path,
    empirical_manifest: Path,
    empirical_report: Path,
    upgrade_manifest: Path,
    upgrade_report: Path,
    traceability_report: Path,
) -> list[Gate]:
    empirical = SKILL_SCRIPTS / "run_empirical_gate.py"
    traceability = REPO_ROOT / "scripts" / "check_traceability.py"
    return [
        *forward_gates(forward_report),
        Gate(
            "empirical-adoption-report",
            [
                sys.executable,
                str(empirical),
                "--manifest",
                str(empirical_manifest),
                "--check-report",
                str(empirical_report),
            ],
            required_paths=[empirical, empirical_manifest, empirical_report],
            risk="The empirical adoption report is missing, stale, invalid, or failed.",
        ),
        Gate(
            "empirical-upgrade-report",
            [
                sys.executable,
                str(empirical),
                "--manifest",
                str(upgrade_manifest),
                "--check-report",
                str(upgrade_report),
            ],
            required_paths=[empirical, upgrade_manifest, upgrade_report],
            risk="The empirical upgrade report is missing, stale, invalid, or failed.",
        ),
        Gate(
            "acceptance-traceability-report",
            [
                sys.executable,
                str(traceability),
                "--manifest",
                str(TRACEABILITY_MANIFEST),
                "--check-report",
                str(traceability_report),
            ],
            required_paths=[
                traceability,
                TRACEABILITY_MANIFEST,
                traceability_report,
            ],
            risk="The acceptance traceability report is missing, stale, or failed.",
        ),
    ]


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


def persist_junit(path: Path, report: dict[str, Any]) -> None:
    gates = report["gates"]
    failures = sum(gate["status"] == "failed" for gate in gates)
    errors = sum(gate["status"] in {"blocked", "unverified"} for gate in gates)
    suite = ET.Element(
        "testsuite",
        {
            "name": f"openapi-engineering-{report['tier']}",
            "tests": str(len(gates)),
            "failures": str(failures),
            "errors": str(errors),
        },
    )
    for gate in gates:
        case = ET.SubElement(
            suite,
            "testcase",
            {
                "name": gate["name"],
                "classname": f"openapi_engineering.{report['tier']}",
                "time": f"{gate['duration_ms'] / 1000:.3f}",
            },
        )
        if gate["status"] == "failed":
            failure = ET.SubElement(case, "failure", {"message": "gate failed"})
            failure.text = gate["risk"] or "Verification command returned a failure."
        elif gate["status"] in {"blocked", "unverified"}:
            error = ET.SubElement(case, "error", {"message": gate["status"]})
            error.text = gate["risk"] or "Verification capability was unavailable."
    ET.indent(suite)
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    ET.ElementTree(suite).write(
        temporary, encoding="utf-8", xml_declaration=True
    )
    temporary.replace(path)


def run_verification(
    tier: str,
    report_path: Path,
    *,
    gates: Sequence[Gate] | None = None,
    forward_report: Path | None = None,
    empirical_manifest: Path | None = None,
    empirical_report: Path | None = None,
    upgrade_manifest: Path | None = None,
    upgrade_report: Path | None = None,
    traceability_report: Path | None = None,
    junit_path: Path | None = None,
) -> tuple[dict[str, Any], int]:
    report_path = report_path.expanduser().resolve()
    evidence_dir = report_path.parent / f"{report_path.stem}-evidence"
    prepare_evidence_dir(evidence_dir)
    started_at = utc_now()
    results: list[dict[str, Any]] = []

    if gates is None and tier == "forward" and forward_report is None:
        results.append(blocked_tier_gate(tier, evidence_dir / "01-adapter-authorization.log"))
    elif gates is None and tier == "full" and not all(
        (
            forward_report,
            empirical_manifest,
            empirical_report,
            upgrade_manifest,
            upgrade_report,
            traceability_report,
        )
    ):
        results.append(blocked_tier_gate(tier, evidence_dir / "01-release-evidence.log"))
    else:
        if gates is not None:
            selected = list(gates)
        elif tier == "forward":
            selected = forward_gates(forward_report.expanduser().resolve())
        elif tier == "full":
            selected = [
                *deterministic_gates(),
                *full_evidence_gates(
                    forward_report=forward_report.expanduser().resolve(),
                    empirical_manifest=empirical_manifest.expanduser().resolve(),
                    empirical_report=empirical_report.expanduser().resolve(),
                    upgrade_manifest=upgrade_manifest.expanduser().resolve(),
                    upgrade_report=upgrade_report.expanduser().resolve(),
                    traceability_report=traceability_report.expanduser().resolve(),
                ),
            ]
        else:
            selected = deterministic_gates()
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
    if junit_path:
        persist_junit(junit_path, report)
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
    parser.add_argument(
        "--forward-report",
        type=Path,
        help="Existing combined forward report to validate.",
    )
    parser.add_argument("--empirical-manifest", type=Path)
    parser.add_argument("--empirical-report", type=Path)
    parser.add_argument("--upgrade-manifest", type=Path)
    parser.add_argument("--upgrade-report", type=Path)
    parser.add_argument("--traceability-report", type=Path)
    parser.add_argument("--junit", type=Path, help="Optional JUnit XML output path.")
    args = parser.parse_args()
    report_path = args.report or (
        REPO_ROOT / "docs" / "verifications" / "latest" / f"{args.tier}-report.json"
    )
    report, exit_code = run_verification(
        args.tier,
        report_path,
        forward_report=args.forward_report,
        empirical_manifest=args.empirical_manifest,
        empirical_report=args.empirical_report,
        upgrade_manifest=args.upgrade_manifest,
        upgrade_report=args.upgrade_report,
        traceability_report=args.traceability_report,
        junit_path=args.junit,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
