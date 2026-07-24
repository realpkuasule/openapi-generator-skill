from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


SAMPLE_INTERVAL_SECONDS = 0.05
TERMINATE_GRACE_SECONDS = 2.0
MAX_CAPTURE_CHARS = 2 * 1024 * 1024


@dataclass(frozen=True)
class ControlledProcessResult:
    returncode: int
    stdout: str
    stderr: str
    resources: dict[str, object]


class ProcessLimitExceeded(RuntimeError):
    def __init__(self, reason: str, resources: dict[str, object]):
        super().__init__(reason)
        self.reason = reason
        self.resources = resources


def resource_evidence(
    *,
    measurement_status: str,
    peak_rss_bytes: int | None,
    warning_limit_bytes: int,
    hard_limit_bytes: int,
    warning_exceeded: bool,
    termination_reason: str,
    duration_ms: int,
    process_group_reclaimed: bool,
) -> dict[str, object]:
    return {
        "measurement_status": measurement_status,
        "peak_rss_bytes": peak_rss_bytes,
        "warning_limit_bytes": warning_limit_bytes,
        "hard_limit_bytes": hard_limit_bytes,
        "warning_exceeded": warning_exceeded,
        "termination_reason": termination_reason,
        "duration_ms": duration_ms,
        "process_group_reclaimed": process_group_reclaimed,
    }


def not_run_evidence(
    warning_limit_bytes: int, hard_limit_bytes: int, *, reason: str = "not-run"
) -> dict[str, object]:
    return resource_evidence(
        measurement_status="not-run",
        peak_rss_bytes=None,
        warning_limit_bytes=warning_limit_bytes,
        hard_limit_bytes=hard_limit_bytes,
        warning_exceeded=False,
        termination_reason=reason,
        duration_ms=0,
        process_group_reclaimed=False,
    )


def _process_tree_rss_bytes(root_pid: int) -> int | None:
    if os.name == "nt":
        return None
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,rss="],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    rows: dict[int, tuple[int, int]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            pid, parent_pid, rss_kib = (int(field) for field in fields)
        except ValueError:
            continue
        rows[pid] = (parent_pid, max(0, rss_kib) * 1024)
    if root_pid not in rows:
        return 0
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent_pid, _rss) in rows.items():
            if parent_pid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return sum(rows[pid][1] for pid in descendants)


def _terminate_owned_group(process: subprocess.Popen[str]) -> bool:
    if process.poll() is not None:
        return False
    if os.name == "nt":
        process.terminate()
    else:
        try:
            group_id = os.getpgid(process.pid)
        except ProcessLookupError:
            return False
        if group_id != process.pid:
            raise RuntimeError("Refusing to terminate a process group not owned by the watcher.")
        os.killpg(group_id, signal.SIGTERM)
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    return True


def _read_bounded(handle) -> str:
    handle.seek(0)
    return handle.read(MAX_CAPTURE_CHARS + 1)[:MAX_CAPTURE_CHARS]


def run_controlled(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None,
    timeout_seconds: float,
    warning_limit_bytes: int,
    hard_limit_bytes: int,
) -> ControlledProcessResult:
    if (
        not command
        or timeout_seconds <= 0
        or warning_limit_bytes <= 0
        or hard_limit_bytes <= warning_limit_bytes
    ):
        raise ValueError("Controlled process limits are invalid.")
    if os.name == "nt":
        evidence = resource_evidence(
            measurement_status="unsupported",
            peak_rss_bytes=None,
            warning_limit_bytes=warning_limit_bytes,
            hard_limit_bytes=hard_limit_bytes,
            warning_exceeded=False,
            termination_reason="measurement-unsupported",
            duration_ms=0,
            process_group_reclaimed=False,
        )
        raise ProcessLimitExceeded("measurement-unsupported", evidence)

    started = time.monotonic()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+", encoding="utf-8"
    ) as stderr_file:
        try:
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            evidence = not_run_evidence(
                warning_limit_bytes, hard_limit_bytes, reason="launch-failed"
            )
            raise ProcessLimitExceeded("launch-failed", evidence) from exc

        if process.stdin is not None:
            try:
                if input_text is not None:
                    process.stdin.write(input_text)
                    process.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()

        peak_rss_bytes = 0
        warning_exceeded = False
        reason: str | None = None
        while process.poll() is None:
            measured = _process_tree_rss_bytes(process.pid)
            if measured is None:
                reason = "measurement-unsupported"
                break
            peak_rss_bytes = max(peak_rss_bytes, measured)
            warning_exceeded = warning_exceeded or measured > warning_limit_bytes
            if measured > hard_limit_bytes:
                reason = "rss-hard-limit"
                break
            if time.monotonic() - started > timeout_seconds:
                reason = "timeout"
                break
            time.sleep(SAMPLE_INTERVAL_SECONDS)

        reclaimed = False
        if reason is not None:
            reclaimed = _terminate_owned_group(process)
        else:
            process.wait()
            measured = _process_tree_rss_bytes(process.pid)
            if measured is not None:
                peak_rss_bytes = max(peak_rss_bytes, measured)
                warning_exceeded = warning_exceeded or measured > warning_limit_bytes

        duration_ms = int((time.monotonic() - started) * 1000)
        evidence = resource_evidence(
            measurement_status="unsupported" if reason == "measurement-unsupported" else "measured",
            peak_rss_bytes=None if reason == "measurement-unsupported" else peak_rss_bytes,
            warning_limit_bytes=warning_limit_bytes,
            hard_limit_bytes=hard_limit_bytes,
            warning_exceeded=False if reason == "measurement-unsupported" else warning_exceeded,
            termination_reason=reason or "exited",
            duration_ms=duration_ms,
            process_group_reclaimed=reclaimed,
        )
        if reason is not None:
            raise ProcessLimitExceeded(reason, evidence)
        return ControlledProcessResult(
            returncode=process.returncode,
            stdout=_read_bounded(stdout_file),
            stderr=_read_bounded(stderr_file),
            resources=evidence,
        )
