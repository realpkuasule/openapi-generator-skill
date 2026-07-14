from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.support import parse_json_output, run_script, snapshot_tree


class CompareGenerationTests(unittest.TestCase):
    def test_comparison_classifies_files_and_preserves_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline"
            candidate = root / "candidate"
            baseline.mkdir()
            candidate.mkdir()
            (baseline / "removed.txt").write_text("old", encoding="utf-8")
            (baseline / "changed.txt").write_text("before", encoding="utf-8")
            (baseline / "same.txt").write_text("same", encoding="utf-8")
            (candidate / "added.txt").write_text("new", encoding="utf-8")
            (candidate / "changed.txt").write_text("after", encoding="utf-8")
            (candidate / "same.txt").write_text("same", encoding="utf-8")
            before_baseline = snapshot_tree(baseline)
            before_candidate = snapshot_tree(candidate)

            result = run_script(
                "compare_generation.py", str(baseline), str(candidate)
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = parse_json_output(result)
            self.assertEqual(
                payload["summary"],
                {"added": 1, "removed": 1, "changed": 1, "unchanged": 1},
            )
            states = {item["path"]: item["state"] for item in payload["files"]}
            self.assertEqual(
                states,
                {
                    "added.txt": "added",
                    "changed.txt": "changed",
                    "removed.txt": "removed",
                    "same.txt": "unchanged",
                },
            )
            self.assertEqual(snapshot_tree(baseline), before_baseline)
            self.assertEqual(snapshot_tree(candidate), before_candidate)

    def test_output_is_stable_and_ignores_noise(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline"
            candidate = root / "candidate"
            baseline.mkdir()
            candidate.mkdir()
            (baseline / ".DS_Store").write_text("a", encoding="utf-8")
            (candidate / ".DS_Store").write_text("b", encoding="utf-8")
            first = run_script(
                "compare_generation.py", str(baseline), str(candidate)
            )
            second = run_script(
                "compare_generation.py", str(baseline), str(candidate)
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(parse_json_output(first)["files"], [])

    def test_missing_directory_returns_json_error(self) -> None:
        result = run_script(
            "compare_generation.py", "/missing/baseline", "/missing/candidate"
        )
        self.assertEqual(result.returncode, 2)
        payload = parse_json_output(result)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "invalid-directory")


if __name__ == "__main__":
    unittest.main()
