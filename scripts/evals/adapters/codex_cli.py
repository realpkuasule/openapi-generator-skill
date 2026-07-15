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
    clean_environment,
    continuation_prompt,
    final_observation_prompt,
    initial_prompt,
    parse_json_object,
    probe_cli,
    resolve_binary,
)


class CodexCliAdapter:
    name = "codex"

    def __init__(self, *, binary: str = "codex", model: str = "gpt-5.4-mini") -> None:
        self.binary = binary
        self.model = model
        self._capability: AdapterCapability | None = None

    def probe(self) -> AdapterCapability:
        if self._capability is None:
            self._capability = probe_cli(self.binary)
        return self._capability

    @staticmethod
    def _thread_id(stdout: str) -> str:
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and isinstance(
                event.get("thread_id"), str
            ):
                return event["thread_id"]
        raise ValueError("Codex JSONL did not contain a thread.started event.")

    @staticmethod
    def _read_message(path: Path) -> str:
        if not path.is_file():
            raise ValueError("Codex did not write its final message file.")
        return path.read_text(encoding="utf-8").strip()

    def invoke(self, request: EvalRequest, timeout_seconds: int) -> dict[str, Any]:
        binary = resolve_binary(self.binary)
        if binary is None:
            raise OSError(f"CLI executable not found: {self.binary}")
        with tempfile.TemporaryDirectory(prefix="openapi-eval-codex-") as directory:
            root = Path(directory)
            isolated_home = root / "home"
            isolated_home.mkdir()
            codex_home = root / "codex-home"
            codex_home.mkdir()
            source_home = Path(
                os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
            ).expanduser()
            auth = source_home / "auth.json"
            if auth.is_file():
                shutil.copy2(auth, codex_home / "auth.json")
            env = clean_environment()
            env["HOME"] = str(isolated_home)
            env["CODEX_HOME"] = str(codex_home)
            runner = DeadlineRunner(timeout_seconds, env)
            prefix = [
                binary,
                "-a",
                "never",
                "-s",
                "read-only",
                "-c",
                'model_reasoning_effort="low"',
                "-m",
                self.model,
                "exec",
            ]

            output = root / "message.txt"
            initial = [
                *prefix,
                "--skip-git-repo-check",
                "--ignore-user-config",
                "--ignore-rules",
                "-C",
                str(request.project_root),
                "--json",
                "-o",
                str(output),
                "-",
            ]
            completed = runner.run(
                initial, cwd=request.project_root, input_text=initial_prompt(request)
            )
            thread_id = self._thread_id(completed.stdout)
            assistant_interview = [self._read_message(output)]

            for answer in request.interview_answers[:-1]:
                command = [
                    *prefix,
                    "resume",
                    "--json",
                    "--skip-git-repo-check",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "-o",
                    str(output),
                    thread_id,
                    "-",
                ]
                runner.run(
                    command,
                    cwd=request.project_root,
                    input_text=continuation_prompt(answer.content, final_answer=False),
                )
                assistant_interview.append(self._read_message(output))

            runner.run(
                [
                    *prefix,
                    "resume",
                    "--json",
                    "--skip-git-repo-check",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "-o",
                    str(output),
                    thread_id,
                    "-",
                ],
                cwd=request.project_root,
                input_text=continuation_prompt(
                    request.interview_answers[-1].content, final_answer=True
                ),
            )
            proposal = self._read_message(output)

            runner.run(
                [
                    *prefix,
                    "resume",
                    "--json",
                    "--skip-git-repo-check",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "-o",
                    str(output),
                    thread_id,
                    "-",
                ],
                cwd=request.project_root,
                input_text=final_observation_prompt(request.approval),
            )
            final_content = self._read_message(output)
            observation = parse_json_object(final_content, platform="Codex")
            return build_result(
                request,
                assistant_interview=assistant_interview,
                proposal=proposal,
                final_content=final_content,
                observation=observation,
            )
