#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

LOCAL_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(LOCAL_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCAL_REPO_ROOT))

from scripts.evals.adapters.base import EvalAdapter, EvalRequest, InterviewAnswer
from scripts.evals.adapters.claude_cli import ClaudeCliAdapter
from scripts.evals.adapters.codex_cli import CodexCliAdapter
from scripts.evals.adapters.fake import FakeAdapter
from scripts.evals.harness import harness_digest
from scripts.evals.load_cases import (
    DEFAULT_EVAL_ROOT,
    REPO_ROOT,
    EvalCaseError,
    fixture_path,
    load_cases,
)
from scripts.evals.sandbox import sandbox_project, tree_digest as project_tree_digest
from scripts.evals.score_result import EvalResultError, score_result, validate_result
from scripts.install_skill import tree_digest as skill_tree_digest


SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering"
REPORT_VERSION = 2


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
            interview_answers=tuple(
                InterviewAnswer(
                    content=answer["content"],
                    covers_questions=tuple(answer["covers_questions"]),
                )
                for answer in case["input"]["interview_answers"]
            ),
            approval=case["input"]["approval"],
            project_root=project,
            skill_root=SKILL_ROOT,
        )
        before = project_tree_digest(project)
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
        after = project_tree_digest(project)

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
    cases: Sequence[dict[str, Any]],
    adapter: EvalAdapter,
    *,
    timeout_seconds: int,
    samples: int = 1,
    initial_results: Sequence[dict[str, Any]] = (),
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], int]:
    plan = [case for _sample in range(samples) for case in cases]
    case_ids = [case["id"] for case in cases]
    if len(initial_results) > len(plan):
        raise ValueError("checkpoint contains more results than the evaluation plan")
    results = [copy.deepcopy(result) for result in initial_results]
    for result, case in zip(results, plan):
        validate_result(result)
        if result["case_id"] != case["id"] or result["input_sha256"] != input_digest(
            case
        ):
            raise ValueError("checkpoint results are not an exact evaluation-plan prefix")
        if result["adapter"] != adapter.name:
            raise ValueError("checkpoint result adapter does not match the requested adapter")

    for case in plan[len(results) :]:
        results.append(run_evaluation(case, adapter, timeout_seconds=timeout_seconds))
        if checkpoint is not None:
            partial, _exit_code = build_run_report(
                adapter,
                samples=samples,
                timeout_seconds=timeout_seconds,
                case_ids=case_ids,
                requested_results=len(plan),
                results=results,
            )
            checkpoint(partial)

    return build_run_report(
        adapter,
        samples=samples,
        timeout_seconds=timeout_seconds,
        case_ids=case_ids,
        requested_results=len(plan),
        results=results,
    )


def build_run_report(
    adapter: EvalAdapter,
    *,
    samples: int,
    timeout_seconds: int,
    case_ids: Sequence[str],
    requested_results: int,
    results: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    if len(results) > requested_results:
        raise ValueError("completed results exceed the requested evaluation plan")
    statuses = {result["status"] for result in results}
    complete = len(results) == requested_results
    if not complete or "blocked" in statuses:
        status, exit_code = "blocked", 2
    elif "failed" in statuses:
        status, exit_code = "failed", 1
    else:
        status, exit_code = "passed", 0
    return {
        "report_version": REPORT_VERSION,
        "adapter": adapter.name,
        "skill_sha256": skill_tree_digest(SKILL_ROOT),
        "harness_sha256": harness_digest(),
        "samples": samples,
        "timeout_seconds": timeout_seconds,
        "case_ids": list(case_ids),
        "requested_results": requested_results,
        "completed_results": len(results),
        "status": status,
        "results": [copy.deepcopy(result) for result in results],
    }, exit_code


def retry_nonpassing_results(
    cases: Sequence[dict[str, Any]],
    adapter: EvalAdapter,
    *,
    timeout_seconds: int,
    samples: int,
    existing_results: Sequence[dict[str, Any]],
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], int]:
    plan = [case for _sample in range(samples) for case in cases]
    case_ids = [case["id"] for case in cases]
    if len(existing_results) != len(plan):
        raise ValueError("retry-nonpassing requires a complete evaluation checkpoint")
    results = [copy.deepcopy(result) for result in existing_results]
    for result, case in zip(results, plan):
        validate_result(result)
        if result["adapter"] != adapter.name:
            raise ValueError("checkpoint result adapter does not match the requested adapter")
        if result["case_id"] != case["id"] or result["input_sha256"] != input_digest(
            case
        ):
            raise ValueError("checkpoint results are not an exact evaluation-plan prefix")

    for index, case in enumerate(plan):
        if results[index]["status"] == "passed":
            continue
        results[index] = run_evaluation(
            case, adapter, timeout_seconds=timeout_seconds
        )
        if checkpoint is not None:
            partial, _exit_code = build_run_report(
                adapter,
                samples=samples,
                timeout_seconds=timeout_seconds,
                case_ids=case_ids,
                requested_results=len(plan),
                results=results,
            )
            checkpoint(partial)

    return build_run_report(
        adapter,
        samples=samples,
        timeout_seconds=timeout_seconds,
        case_ids=case_ids,
        requested_results=len(plan),
        results=results,
    )


def load_resume_results(
    path: Path,
    cases: Sequence[dict[str, Any]],
    adapter: EvalAdapter,
    *,
    timeout_seconds: int,
    samples: int,
) -> list[dict[str, Any]]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"resume checkpoint cannot be loaded: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError("resume checkpoint must be a JSON object")
    plan = [case for _sample in range(samples) for case in cases]
    expected = {
        "report_version": REPORT_VERSION,
        "adapter": adapter.name,
        "skill_sha256": skill_tree_digest(SKILL_ROOT),
        "harness_sha256": harness_digest(),
        "samples": samples,
        "timeout_seconds": timeout_seconds,
        "case_ids": [case["id"] for case in cases],
        "requested_results": len(plan),
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise ValueError(f"resume checkpoint {field} does not match this run")
    results = report.get("results")
    if not isinstance(results, list):
        raise ValueError("resume checkpoint results must be an array")
    if report.get("completed_results") != len(results):
        raise ValueError("resume checkpoint completed_results does not match results")
    if len(results) > len(plan):
        raise ValueError("resume checkpoint exceeds the requested evaluation plan")
    if len(results) < len(plan) and report.get("status") != "blocked":
        raise ValueError("an incomplete resume checkpoint must have blocked status")
    for result, case in zip(results, plan):
        try:
            validate_result(result)
        except (EvalResultError, TypeError) as exc:
            raise ValueError(f"resume checkpoint result is invalid: {exc}") from exc
        if result["adapter"] != adapter.name:
            raise ValueError("resume checkpoint result adapter does not match this run")
        if result["case_id"] != case["id"] or result["input_sha256"] != input_digest(
            case
        ):
            raise ValueError("resume checkpoint is not an exact evaluation-plan prefix")
    return [copy.deepcopy(result) for result in results]


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
    parser.add_argument("--adapter", choices=("fake", "codex", "claude"), default="fake")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--fake-result-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-nonpassing", action="store_true")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if args.samples < 1:
        parser.error("--samples must be positive")
    if args.resume and not args.report:
        parser.error("--resume requires --report")
    if args.retry_nonpassing and not args.resume:
        parser.error("--retry-nonpassing requires --resume")
    try:
        cases = load_cases(DEFAULT_EVAL_ROOT, args.case)
    except EvalCaseError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, sort_keys=True))
        return 2
    if args.adapter == "codex":
        adapter: EvalAdapter = CodexCliAdapter()
    elif args.adapter == "claude":
        adapter = ClaudeCliAdapter()
    else:
        adapter = FakeAdapter(
            args.fake_result_dir.expanduser().resolve() if args.fake_result_dir else None,
            dry_run=args.dry_run,
        )
    report_path = args.report.expanduser().resolve() if args.report else None
    try:
        initial_results = (
            load_resume_results(
                report_path,
                cases,
                adapter,
                timeout_seconds=args.timeout,
                samples=args.samples,
            )
            if args.resume and report_path is not None
            else []
        )
        requested_results = len(cases) * args.samples
        if report_path is not None and not args.resume:
            initial_report, _initial_exit = build_run_report(
                adapter,
                samples=args.samples,
                timeout_seconds=args.timeout,
                case_ids=[case["id"] for case in cases],
                requested_results=requested_results,
                results=[],
            )
            write_report(report_path, initial_report)
        checkpoint = (
            (lambda value: write_report(report_path, value))
            if report_path is not None
            else None
        )
        if args.retry_nonpassing:
            report, exit_code = retry_nonpassing_results(
                cases,
                adapter,
                timeout_seconds=args.timeout,
                samples=args.samples,
                existing_results=initial_results,
                checkpoint=checkpoint,
            )
        else:
            report, exit_code = run_many(
                cases,
                adapter,
                timeout_seconds=args.timeout,
                samples=args.samples,
                initial_results=initial_results,
                checkpoint=checkpoint,
            )
    except (OSError, ValueError, EvalResultError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, sort_keys=True))
        return 2
    if report_path is not None:
        write_report(report_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
