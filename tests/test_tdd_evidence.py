from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import tdd_evidence


class TddEvidenceTests(unittest.TestCase):
    def test_refresh_records_artifact_digest_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            artifact = evidence / "red.log"
            artifact.write_bytes(b"expected failure\n")
            manifest = evidence / "manifest.json"
            manifest.write_text('{"schema_version":1,"tasks":[]}', encoding="utf-8")

            refreshed = tdd_evidence.refresh_manifest(manifest, evidence)

            self.assertEqual(len(refreshed["artifacts"]), 1)
            row = refreshed["artifacts"][0]
            self.assertEqual(row["bytes"], len(b"expected failure\n"))
            self.assertEqual(
                row["sha256"], hashlib.sha256(b"expected failure\n").hexdigest()
            )
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), refreshed)

    def test_refresh_is_byte_stable_and_does_not_inventory_itself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            (evidence / "nested").mkdir()
            (evidence / "nested" / "green.log").write_text("ok\n", encoding="utf-8")
            manifest = evidence / "manifest.json"
            manifest.write_text('{"schema_version":1,"tasks":[]}', encoding="utf-8")

            tdd_evidence.refresh_manifest(manifest, evidence)
            first = manifest.read_bytes()
            tdd_evidence.refresh_manifest(manifest, evidence)

            self.assertEqual(manifest.read_bytes(), first)
            paths = [row["path"] for row in json.loads(first)["artifacts"]]
            self.assertNotIn(str(manifest), paths)


if __name__ == "__main__":
    unittest.main()
