from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterCapability:
    available: bool
    version: str
    reason: str | None


@dataclass(frozen=True)
class EvalRequest:
    case_id: str
    prompt: str
    project_facts: tuple[str, ...]
    adversarial_inputs: tuple[str, ...]
    project_root: Path
    skill_root: Path


class EvalAdapter(Protocol):
    name: str

    def probe(self) -> AdapterCapability: ...

    def invoke(self, request: EvalRequest, timeout_seconds: int) -> dict[str, Any]: ...
