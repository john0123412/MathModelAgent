"""Regression tests for the LaTeX preflight scripts added to the 6verity skill.

These scripts (`check_latex_refs.py`, `check_latex_env.py`) were ported verbatim
from the `mathmodel-latex-skill` open-source collection (MIT) into
`skills/6verity/scripts/` to strengthen the LaTeX-engine acceptance gate.

The tests assert:
1. Both scripts load and expose their documented CLI (--help exits 0).
2. `check_latex_refs.py` passes a clean .tex (valid label + cite) and fails a
   .tex with a dangling cross-reference (exit-code contract used by 6verity).

They do NOT require a LaTeX toolchain (xelatex/kpsewhich) to be installed, so
they stay green in CI and on machines without TeX Live.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
CHECK_REFS = SCRIPTS_DIR / "check_latex_refs.py"
CHECK_ENV = SCRIPTS_DIR / "check_latex_env.py"


class LatexPreflightScriptsTests(unittest.TestCase):
    def test_refs_script_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECK_REFS), "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tex", result.stdout)

    def test_env_script_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECK_ENV), "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--contest", result.stdout)

    def test_refs_script_passes_clean_tex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main.tex"
            main.write_text(
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "\\section{Intro}\\label{sec:intro}\n"
                "See \\ref{sec:intro} and \\cite{knuth}.\n"
                "\\begin{thebibliography}{1}\n"
                "\\bibitem{knuth} D. Knuth, 1984.\n"
                "\\end{thebibliography}\n"
                "\\end{document}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(CHECK_REFS), str(main)],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASSED", result.stdout)

    def test_refs_script_fails_dangling_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main.tex"
            main.write_text(
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "\\section{Intro}\\label{sec:intro}\n"
                "See \\ref{sec:missing} which does not exist.\n"
                "\\end{document}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(CHECK_REFS), str(main)],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("MISSING LABEL TARGETS", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
