#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

LOCAL_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(LOCAL_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCAL_REPO_ROOT))

from scripts.evals.adapters.base import EvalAdapter, EvalRequest
from scripts.evals.adapters.fake import FakeAdapter
from scripts.evals.load_cases import DEFAULT_EVAL_ROOT, EvalCaseError, REPO_ROOT, fixture_path, load_cases
from scripts.evals.sandbox import sandbox_project, tree_digest
from scripts.evals.score_result import EvalResultError, score_result


SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering"


def input_digest(case: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            case["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def empty_result(
    request: EvalRequest,
    *,
    adapter: str,
    version: str,
    status: str,
    unverified: list[str],
) -> dict[str, Any]:
    return {
        "case_id": request.case_id,
        "adapter": adapter,
        "platform_version": version,
        "input_sha256": "0" * 64,
        "status": status,
        "turns": [],
        "observed_modes": [],
        "question_coverage": [],
        "boundary_summary": {"fields": [], "included": [], "excluded": []},
        "approval_transition": {"sequence": [], "reapproval_requested": False},
        "tool_decision": {"primary_strategy": "no-codegen", "boundaries": []},
        "actions": [],
        "prohibited_actions_violated": [],
        "file_hashes": {"before": "0" * 64, "after": "0" * 64},
        "completion_report": None,
        "scores": {},
        "unverified": unverified,
    }


def run_evaluation(
    case: dict[str, Any], adapter: EvalAdapter, *, timeout_seconds: int
) -> dict[str, Any]:
    capability = adapter.probe()
    fixture = fixture_path(case)
    with sandbox_project(fixture) as project:
        request = EvalRequest(
            case_id=case["id"],
            prompt=case["input"]["prompt"],
            project_facts=tuple(case["input"]["project_facts"]),
            adversarial_inputs=tuple(case["input"].get("adversarial_inputs", [])),
            project_root=project,
            skill_root=SKILL_ROOT,
        )
        before = tree_digest(project)
        if not capability.available:
            raw = empty_result(
                request,
                adapter=adapter.name,
                version=capability.version,
                status="blocked",
                unverified=[capability.reason or "adapter unavailable"],
            )
        else:
            try:
                raw = adapter.invoke(request, timeout_seconds)
                if not isinstance(raw, dict):
                    raise ValueError("Adapter result must be an object.")
                raw = copy.deepcopy(raw)
            except TimeoutError:
                raw = empty_result(
                    request,
                    adapter=adapter.name,
                    version=capability.version,
                    status="failed",
                    unverified=["adapter timeout"],
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raw = empty_result(
                    request,
                    adapter=adapter.name,
                    version=capability.version,
                    status="blocked",
                    unverified=[f"adapter error: {exc}"],
                )
        after = tree_digest(project)

    raw["case_id"] = case["id"]
    raw["adapter"] = adapter.name
    raw["platform_version"] = capability.version
    raw["input_sha256"] = input_digest(case)
    raw["file_hashes"] = {"before": before, "after": after}
    try:
        return score_result(case, raw)
    except EvalResultError as exc:
        fallback = empty_result(
            request,
            adapter=adapter.name,
            version=capability.version,
            status="failed",
            unverified=[f"invalid adapter result: {exc}"],
        )
        fallback["input_sha256"] = input_digest(case)
        fallback["file_hashes"] = {"before": before, "after": after}
        return score_result(case, fallback)


def run_many(
    cases: Sequence[dict[str, Any]], adapter: EvalAdapter, *, timeout_seconds: int
) -> tuple[dict[str, Any], int]:
    results = [
        run_evaluation(case, adapter, timeout_seconds=timeout_seconds) for case in cases
    ]
    statuses = {result["status"] for result in results}
    if "blocked" in statuses:
        status, exit_code = "blocked", 2
    elif "failed" in statuses:
        status, exit_code = "failed", 1
    else:
        status, exit_code = "passed", 0
    return {
        "report_version": 1,
        "adapter": adapter.name,
        "status": status,
        "results": results,
    }, exit_code


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated OpenAPI engineering skill evals.")
    parser.add_argument("--adapter", choices=("fake",), default="fake")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--fake-result-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        cases = load_cases(DEFAULT_EVAL_ROOT, args.case)
    except EvalCaseError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, sort_keys=True))
        return 2
    adapter = FakeAdapter(
        args.fake_result_dir.expanduser().resolve() if args.fake_result_dir else None,
        dry_run=args.dry_run,
    )
    report, exit_code = run_many(cases, adapter, timeout_seconds=args.timeout)
    if args.report:
        write_report(args.report.expanduser().resolve(), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
