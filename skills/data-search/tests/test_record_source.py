"""record_source.py 离线单元测试：SHA-256 台账登记、幂等更新与项目边界校验。

全部用例在系统临时目录构造假项目，不访问网络。

运行：backend/.venv/Scripts/python.exe skills/data-search/tests/test_record_source.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_source.py"


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        timeout=30,
    )


class RecordSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        raw = self.project / "data" / "raw"
        raw.mkdir(parents=True)
        self.data_file = raw / "population_2020.csv"
        self.data_file.write_text("year,region,value\n2020,A,1.0\n", encoding="utf-8")
        self.expected_sha = hashlib.sha256(self.data_file.read_bytes()).hexdigest()

    def tearDown(self):
        self._tmp.cleanup()

    def _record(self) -> subprocess.CompletedProcess[str]:
        return _run(
            "--project", str(self.project),
            "--file", "data/raw/population_2020.csv",
            "--source-url", "https://example.org/api/population",
            "--title", "Population Statistics 2020",
            "--publisher", "Example Bureau of Statistics",
            "--license", "CC BY 4.0",
        )

    def test_record_creates_manifest_with_sha256(self):
        proc = self._record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest = json.loads(
            (self.project / "data" / "sources.json").read_text(encoding="utf-8")
        )
        entry = manifest["sources"][0]
        self.assertEqual(entry["sha256"], self.expected_sha)
        self.assertEqual(entry["file"], "data/raw/population_2020.csv")
        self.assertEqual(entry["bytes"], self.data_file.stat().st_size)

    def test_rerecord_updates_in_place(self):
        self._record()
        self.data_file.write_text("year,region,value\n2020,A,2.0\n", encoding="utf-8")
        proc = self._record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest = json.loads(
            (self.project / "data" / "sources.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(manifest["sources"]), 1)
        new_sha = hashlib.sha256(self.data_file.read_bytes()).hexdigest()
        self.assertEqual(manifest["sources"][0]["sha256"], new_sha)
        self.assertNotEqual(new_sha, self.expected_sha)

    def test_rejects_file_outside_project(self):
        outside = Path(tempfile.gettempdir()) / "outside_sources_test.csv"
        outside.write_text("x\n", encoding="utf-8")
        try:
            proc = _run(
                "--project", str(self.project),
                "--file", str(outside),
                "--source-url", "https://example.org/x",
                "--title", "T",
                "--publisher", "P",
            )
            self.assertNotEqual(proc.returncode, 0)
            manifest_path = self.project / "data" / "sources.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["sources"], [])
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
