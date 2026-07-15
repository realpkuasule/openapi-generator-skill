from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .base import AdapterCapability, EvalRequest
from .cli_protocol import (
    DeadlineRunner,
    build_result,
    bundled_forward_schema,
    clean_environment,
    continuation_prompt,
    final_observation_prompt,
    initial_prompt,
    parse_json_object,
    probe_cli,
    resolve_binary,
)


CLAUDE_ENVIRONMENT_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
)


class ClaudeCliAdapter:
    name = "claude"

    def __init__(self, *, binary: str = "claude") -> None:
        self.binary = binary
        self._capability: AdapterCapability | None = None

    def probe(self) -> AdapterCapability:
        if self._capability is None:
            self._capability = probe_cli(self.binary)
        return self._capability

    @staticmethod
    def _payload(stdout: str) -> dict[str, Any]:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Claude did not return JSON output.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Claude JSON output must be an object.")
        return payload

    @staticmethod
    def _content(payload: dict[str, Any]) -> str:
        result = payload.get("result")
        if not isinstance(result, str) or not result.strip():
            raise ValueError("Claude JSON output did not contain a result string.")
        return result.strip()

    def invoke(self, request: EvalRequest, timeout_seconds: int) -> dict[str, Any]:
        binary = resolve_binary(self.binary)
        if binary is None:
            raise OSError(f"CLI executable not found: {self.binary}")
        with tempfile.TemporaryDirectory(prefix="openapi-eval-claude-") as directory:
            root = Path(directory)
            isolated_home = root / "home"
            isolated_home.mkdir()
            claude_home = root / "claude-home"
            claude_home.mkdir()
            source_home = Path(
                os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
            ).expanduser()
            credentials = source_home / ".credentials.json"
            if credentials.is_file():
                shutil.copy2(credentials, claude_home / ".credentials.json")
            env = clean_environment(CLAUDE_ENVIRONMENT_KEYS)
            env["HOME"] = str(isolated_home)
            env["CLAUDE_CONFIG_DIR"] = str(claude_home)
            runner = DeadlineRunner(timeout_seconds, env)
            common = [
                binary,
                "-p",
                "--output-format",
                "json",
                "--permission-mode",
                "plan",
                "--tools",
                "Read,Glob,Grep",
                "--no-chrome",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--add-dir",
                str(request.skill_root),
            ]
            initial = self._payload(
                runner.run(
                    common,
                    cwd=request.project_root,
                    input_text=initial_prompt(request),
                ).stdout
            )
            session_id = initial.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Claude JSON output did not contain a session_id.")
            assistant_interview = [self._content(initial)]

            for answer in request.interview_answers[:-1]:
                payload = self._payload(
                    runner.run(
                        [*common, "--resume", session_id],
                        cwd=request.project_root,
                        input_text=continuation_prompt(answer.content, final_answer=False),
                    ).stdout
                )
                assistant_interview.append(self._content(payload))

            proposed = self._payload(
                runner.run(
                    [*common, "--resume", session_id],
                    cwd=request.project_root,
                    input_text=continuation_prompt(
                        request.interview_answers[-1].content, final_answer=True
                    ),
                ).stdout
            )
            proposal = self._content(proposed)

            final_payload = self._payload(
                runner.run(
                    [
                        *common,
                        "--resume",
                        session_id,
                        "--json-schema",
                        json.dumps(bundled_forward_schema(), ensure_ascii=False),
                    ],
                    cwd=request.project_root,
                    input_text=final_observation_prompt(request.approval),
                ).stdout
            )
            structured = final_payload.get("structured_output")
            if structured is None:
                structured = parse_json_object(
                    self._content(final_payload), platform="Claude"
                )
            if not isinstance(structured, dict):
                raise ValueError("Claude structured output must be an object.")
            final_content = json.dumps(structured, ensure_ascii=False, sort_keys=True)
            return build_result(
                request,
                assistant_interview=assistant_interview,
                proposal=proposal,
                final_content=final_content,
                observation=structured,
            )
