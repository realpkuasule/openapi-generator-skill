from __future__ import annotations

import hashlib
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


IGNORED_PARTS = {".DS_Store", "__pycache__"}


def tree_digest(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


@contextmanager
def sandbox_project(fixture: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="openapi-engineering-eval-") as directory:
        project = Path(directory) / "project"
        shutil.copytree(fixture, project, symlinks=False)
        yield project
