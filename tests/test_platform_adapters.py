from __future__ import annotations

import json
import os
import signal
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.evals.adapters.base import EvalRequest, InterviewAnswer
from scripts.evals.adapters.claude_cli import ClaudeCliAdapter, structured_output_arguments
from scripts.evals.adapters.cli_protocol import (
    DeadlineRunner,
    clean_environment,
    final_observation_prompt,
    normalize_observation,
)
from scripts.evals.adapters.codex_cli import CodexCliAdapter


OBSERVATION = {
    "observed_modes": ["Assess & Select"],
    "boundary_summary": {
        "fields": ["intent", "non_goals", "acceptance_gates", "rollback"],
        "included": ["owned API"],
        "excluded": ["vendor client generation"],
    },
    "tool_decision": {
        "primary_strategy": "governance-only",
        "boundaries": [
            {"boundary": "Owned API", "strategy": "governance-only"}
        ],
    },
    "scope_expansion_requires_reapproval": True,
    "completion_report": None,
    "unverified": [],
}


FAKE_CLI = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import time

args = sys.argv[1:]
stdin = sys.stdin.read()
log = pathlib.Path(os.environ["FAKE_CLI_LOG"])
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")

if "--version" in args:
    print(os.environ.get("FAKE_VERSION", "fake 1.2.3"))
    raise SystemExit(0)

auth_log = os.environ.get("FAKE_AUTH_LOG")
if auth_log:
    kind = os.environ["FAKE_KIND"]
    config = pathlib.Path(
        os.environ["CODEX_HOME" if kind == "codex" else "CLAUDE_CONFIG_DIR"]
    )
    auth = config / ("auth.json" if kind == "codex" else ".credentials.json")
    with pathlib.Path(auth_log).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "exists": auth.is_file(),
            "is_symlink": auth.is_symlink(),
            "content": auth.read_text(encoding="utf-8") if auth.is_file() else None,
            "config": str(config),
            "home": os.environ.get("HOME"),
            "platform_auth_visible": "ANTHROPIC_AUTH_TOKEN" in os.environ,
            "secret_visible": os.environ.get("OPENAPI_EVAL_TEST_SECRET"),
        }) + "\n")

delay = float(os.environ.get("FAKE_CLI_SLEEP", "0"))
if delay:
    time.sleep(delay)

observation = json.loads(os.environ["FAKE_OBSERVATION"])
if os.environ["FAKE_KIND"] == "codex":
    output = pathlib.Path(args[args.index("-o") + 1])
    final = "scope_expansion_requires_reapproval" in stdin
    rendered = json.dumps(observation)
    if final and os.environ.get("FAKE_CODEX_FENCED"):
        rendered = "```json\\n" + rendered + "\\n```"
    output.write_text(
        rendered if final else "One project-specific boundary question?",
        encoding="utf-8",
    )
    if "resume" not in args:
        print(json.dumps({
            "type": "thread.started",
            "thread_id": "11111111-1111-4111-8111-111111111111",
        }))
    print(json.dumps({"type": "turn.completed"}))
else:
    has_schema = "--json-schema" in args
    final = has_schema or "scope_expansion_requires_reapproval" in stdin
    rendered = json.dumps(observation)
    if final and os.environ.get("FAKE_CLAUDE_FENCED"):
        rendered = "```json\\n" + rendered + "\\n```"
    payload = {
        "session_id": "22222222-2222-4222-8222-222222222222",
        "result": rendered if final else "One project-specific boundary question?",
    }
    if final and has_schema and not os.environ.get("FAKE_CLAUDE_FENCED"):
        payload["structured_output"] = observation
    print(json.dumps(payload))
'''


def create_fake_cli(root: Path, *, platform: str = os.name) -> Path:
    if platform == "nt":
        script = root / "fake-cli.py"
        script.write_text(FAKE_CLI, encoding="utf-8", newline="\n")
        launcher = root / "fake-cli.cmd"
        launcher.write_text(
            f'@echo off\n"{sys.executable}" "{script}" %*\n',
            encoding="utf-8",
            newline="\r\n",
        )
        return launcher

    launcher = root / "fake-cli"
    launcher.write_text(FAKE_CLI, encoding="utf-8", newline="\n")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return launcher


class PlatformAdapterTests(unittest.TestCase):
    def test_claude_batch_launcher_avoids_inline_json_schema(self) -> None:
        self.assertEqual(
            structured_output_arguments("claude.cmd", platform="nt"),
            [],
        )
        self.assertEqual(
            structured_output_arguments("claude.bat", platform="nt"),
            [],
        )
        self.assertEqual(
            structured_output_arguments("claude.exe", platform="nt")[0],
            "--json-schema",
        )

    def test_fake_cli_fixture_has_a_windows_launcher(self) -> None:
        windows_root = Path(self.temporary.name) / "windows-fixture"
        windows_root.mkdir()

        launcher = create_fake_cli(windows_root, platform="nt")

        self.assertEqual(launcher.suffix, ".cmd")
        self.assertTrue((windows_root / "fake-cli.py").is_file())
        self.assertIn("%*", launcher.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = create_fake_cli(self.root)
        self.log = self.root / "argv.jsonl"
        self.previous_env = os.environ.copy()
        os.environ.update(
            {
                "FAKE_CLI_LOG": str(self.log),
                "FAKE_OBSERVATION": json.dumps(OBSERVATION),
            }
        )
        self.project = self.root / "project"
        self.project.mkdir()
        self.skill = self.root / "skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text("# fake skill\n", encoding="utf-8")
        self.request = EvalRequest(
            case_id="platform-test",
            prompt="Assess the API boundary.",
            project_facts=("The project owns one HTTP boundary.",),
            adversarial_inputs=(),
            interview_answers=(
                InterviewAnswer("Assessment only; no writes.", (0,)),
                InterviewAnswer("Keep vendor APIs excluded.", (1,)),
            ),
            approval="I approve exactly the proposed read-only boundary.",
            project_root=self.project,
            skill_root=self.skill,
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.previous_env)
        self.temporary.cleanup()

    def _argv(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_codex_adapter_runs_a_resumable_read_only_interview(self) -> None:
        os.environ["FAKE_KIND"] = "codex"
        adapter = CodexCliAdapter(binary=str(self.binary))

        self.assertTrue(adapter.probe().available)
        result = adapter.invoke(self.request, timeout_seconds=10)

        self.assertEqual(result["observed_modes"], ["Assess & Select"])
        self.assertEqual(result["question_coverage"], [0, 1])
        self.assertEqual(
            [turn["phase"] for turn in result["turns"] if turn["role"] == "assistant"],
            ["interview", "interview", "proposed", "execute"],
        )
        calls = self._argv()[1:]
        self.assertEqual(len(calls), 4)
        self.assertTrue(all("read-only" in call for call in calls), calls)
        self.assertTrue(all("--ignore-rules" in call for call in calls), calls)
        self.assertTrue(
            all(
                "-m" in call and call[call.index("-m") + 1] == "gpt-5.4-mini"
                for call in calls
            ),
            calls,
        )
        self.assertTrue(
            all('model_reasoning_effort="low"' in call for call in calls),
            calls,
        )
        self.assertIn("resume", calls[-1])
        self.assertNotIn("--output-schema", calls[-1])
        self.assertTrue(
            all("--skip-git-repo-check" in call for call in calls),
            calls,
        )
        self.assertNotIn("expected", " ".join(" ".join(call) for call in calls).lower())

    def test_codex_adapter_accepts_fenced_json_without_cli_schema_decoding(self) -> None:
        os.environ["FAKE_KIND"] = "codex"
        os.environ["FAKE_CODEX_FENCED"] = "1"

        result = CodexCliAdapter(binary=str(self.binary)).invoke(
            self.request, timeout_seconds=10
        )

        self.assertEqual(result["observed_modes"], ["Assess & Select"])

    def test_claude_adapter_runs_a_resumable_plan_mode_interview(self) -> None:
        os.environ["FAKE_KIND"] = "claude"
        adapter = ClaudeCliAdapter(binary=str(self.binary))

        self.assertTrue(adapter.probe().available)
        result = adapter.invoke(self.request, timeout_seconds=10)

        self.assertEqual(result["tool_decision"]["primary_strategy"], "governance-only")
        self.assertEqual(result["question_coverage"], [0, 1])
        calls = self._argv()[1:]
        self.assertEqual(len(calls), 4)
        self.assertIn("plan", calls[0])
        self.assertIn("--resume", calls[-1])
        if os.name == "nt":
            self.assertNotIn("--json-schema", calls[-1])
        else:
            self.assertIn("--json-schema", calls[-1])
        self.assertNotIn("expected", " ".join(" ".join(call) for call in calls).lower())

    def test_claude_adapter_accepts_fenced_json_when_cli_omits_structured_output(self) -> None:
        os.environ["FAKE_KIND"] = "claude"
        os.environ["FAKE_CLAUDE_FENCED"] = "1"

        result = ClaudeCliAdapter(binary=str(self.binary)).invoke(
            self.request, timeout_seconds=10
        )

        self.assertEqual(result["observed_modes"], ["Assess & Select"])

    def test_platform_credentials_are_copied_into_isolated_config_homes(self) -> None:
        auth_log = self.root / "auth.jsonl"
        os.environ["FAKE_AUTH_LOG"] = str(auth_log)
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "fake-platform-auth"
        os.environ["OPENAPI_EVAL_TEST_SECRET"] = "must-not-reach-cli"

        codex_source = self.root / "source-codex"
        codex_source.mkdir()
        (codex_source / "auth.json").write_text("codex-test-auth", encoding="utf-8")
        os.environ["CODEX_HOME"] = str(codex_source)
        os.environ["FAKE_KIND"] = "codex"
        CodexCliAdapter(binary=str(self.binary)).invoke(self.request, timeout_seconds=10)

        claude_source = self.root / "source-claude"
        claude_source.mkdir()
        (claude_source / ".credentials.json").write_text(
            "claude-test-auth", encoding="utf-8"
        )
        os.environ["CLAUDE_CONFIG_DIR"] = str(claude_source)
        os.environ["FAKE_KIND"] = "claude"
        ClaudeCliAdapter(binary=str(self.binary)).invoke(self.request, timeout_seconds=10)

        rows = [
            json.loads(line)
            for line in auth_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row["exists"] for row in rows), rows)
        self.assertTrue(all(not row["is_symlink"] for row in rows), rows)
        self.assertTrue(all(row["secret_visible"] is None for row in rows), rows)
        self.assertTrue(
            all(not row["platform_auth_visible"] for row in rows[:4]), rows
        )
        self.assertTrue(
            all(row["platform_auth_visible"] for row in rows[4:]), rows
        )
        self.assertTrue(
            all(
                Path(row["home"]).parent == Path(row["config"]).parent
                for row in rows
            ),
            rows,
        )
        self.assertEqual(
            {row["content"] for row in rows},
            {"codex-test-auth", "claude-test-auth"},
        )

    def test_platform_mode_slugs_are_normalized_to_contract_enums(self) -> None:
        os.environ["FAKE_KIND"] = "claude"
        observation = dict(OBSERVATION)
        observation["observed_modes"] = ["audit-and-drift"]
        os.environ["FAKE_OBSERVATION"] = json.dumps(observation)

        result = ClaudeCliAdapter(binary=str(self.binary)).invoke(
            self.request, timeout_seconds=10
        )

        self.assertEqual(result["observed_modes"], ["Audit & Drift"])

        observation["observed_modes"] = ["assess_and_select"]
        os.environ["FAKE_OBSERVATION"] = json.dumps(observation)
        result = ClaudeCliAdapter(binary=str(self.binary)).invoke(
            self.request, timeout_seconds=10
        )
        self.assertEqual(result["observed_modes"], ["Assess & Select"])

        observation["observed_modes"] = ["audit & drift"]
        os.environ["FAKE_OBSERVATION"] = json.dumps(observation)
        result = ClaudeCliAdapter(binary=str(self.binary)).invoke(
            self.request, timeout_seconds=10
        )
        self.assertEqual(result["observed_modes"], ["Audit & Drift"])

    def test_platform_observation_metadata_is_projected_to_the_strict_contract(self) -> None:
        observation = json.loads(json.dumps(OBSERVATION))
        observation["observed_modes"].append("governance-only")
        observation["boundary_summary"]["boundary_strategies"] = []
        observation["tool_decision"]["boundaries"][0].update(
            {"confidence": "high", "conditions": [], "rationale": []}
        )

        normalized = normalize_observation(observation)

        self.assertEqual(normalized["observed_modes"], ["Assess & Select"])
        self.assertNotIn("boundary_strategies", normalized["boundary_summary"])
        self.assertEqual(
            normalized["tool_decision"]["boundaries"],
            [{"boundary": "Owned API", "strategy": "governance-only"}],
        )

    def test_missing_binary_is_blocked_and_timeout_is_not_misreported(self) -> None:
        missing = CodexCliAdapter(binary=str(self.root / "missing")).probe()
        self.assertFalse(missing.available)
        self.assertIn("not found", missing.reason or "")

        os.environ["FAKE_KIND"] = "claude"
        os.environ["FAKE_CLI_SLEEP"] = "2"
        with self.assertRaises(TimeoutError):
            ClaudeCliAdapter(binary=str(self.binary)).invoke(
                self.request, timeout_seconds=1
            )

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-only")
    def test_deadline_runner_terminates_the_process_group_on_timeout(self) -> None:
        child_pid_file = self.root / "child.pid"
        parent = """
import pathlib
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
time.sleep(60)
"""
        runner = DeadlineRunner(1, clean_environment())

        with self.assertRaises(TimeoutError):
            runner.run(
                [sys.executable, "-c", parent, str(child_pid_file)],
                cwd=self.root,
            )

        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("timed-out CLI child process was left running")
        finally:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_deadline_runner_reclaims_the_process_group_when_interrupted(self) -> None:
        process = mock.Mock()
        process.communicate.side_effect = [KeyboardInterrupt(), ("", "")]
        runner = DeadlineRunner(10, clean_environment())

        with mock.patch(
            "scripts.evals.adapters.cli_protocol.subprocess.Popen",
            return_value=process,
        ), mock.patch.object(
            runner, "_terminate_process_group"
        ) as terminate:
            with self.assertRaises(KeyboardInterrupt):
                runner.run(["fake-cli"], cwd=self.root)

        terminate.assert_called_once_with(process)
        self.assertEqual(process.communicate.call_count, 2)

    def test_final_prompt_names_only_the_neutral_observation_contract(self) -> None:
        prompt = final_observation_prompt("I approve the proposed boundary.")

        for field in (
            "observed_modes",
            "boundary_summary",
            "tool_decision",
            "scope_expansion_requires_reapproval",
            "completion_report",
            "unverified",
        ):
            self.assertIn(field, prompt)
        self.assertIn('"boundary": "<project boundary>"', prompt)
        self.assertIn("denied permission", prompt)
        self.assertIn("Never emit the illustrative", prompt)
        self.assertIn("security finding belongs in included", prompt)
        self.assertIn("target project boundary", prompt)
        self.assertIn("exactly two keys", prompt)
        self.assertIn("never becomes primary merely because", prompt)
        self.assertIn("strategy it would actually use after reapproval", prompt)
        self.assertIn("hand-written adapters use language-native", prompt)
        self.assertIn("Do not emit a speculative future candidate", prompt)
        self.assertIn("does not itself select openapi-generator", prompt)
        self.assertIn("strategy assessment include Assess & Select", prompt)
        self.assertIn("preserve project-specific names", prompt)
        self.assertNotIn('"primary_strategy": "governance-only"', prompt)
        self.assertNotIn('"strategy": "governance-only"', prompt)
        self.assertIn("official SDK", prompt)
        self.assertIn("recommendation in included", prompt)
        self.assertIn("code generation", prompt)
        self.assertIn("explicitly in excluded", prompt)
        self.assertNotIn("expected", prompt.lower())


if __name__ == "__main__":
    unittest.main()
