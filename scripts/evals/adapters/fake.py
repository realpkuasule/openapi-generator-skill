from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AdapterCapability, EvalRequest


class FakeAdapter:
    name = "fake"

    def __init__(self, result_dir: Path | None, *, dry_run: bool = False) -> None:
        self.result_dir = result_dir
        self.dry_run = dry_run

    def probe(self) -> AdapterCapability:
        if self.dry_run:
            return AdapterCapability(False, "fake-1", "dry-run")
        if self.result_dir is None or not self.result_dir.is_dir():
            return AdapterCapability(False, "fake-1", "fake result directory is unavailable")
        return AdapterCapability(True, "fake-1", None)

    def invoke(self, request: EvalRequest, timeout_seconds: int) -> dict[str, Any]:
        if self.result_dir is None:
            raise OSError("Fake result directory is unavailable.")
        path = self.result_dir / f"{request.case_id}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Fake adapter result must be an object.")
        return value
