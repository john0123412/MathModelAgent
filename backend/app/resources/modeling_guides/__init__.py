"""Modeling guides loader (roadmap batch D).

Guides are small, phase-typed markdown files under this package.
They are loaded by Modeler/Coder at runtime, not just copied to skills/.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

GUIDE_DIR = Path(__file__).parent

# Map problem diagnostic profiles / phases to guide files
_GUIDE_MAP: dict[str, list[str]] = {
    "deterministic": ["01_deterministic_baseline.md"],
    "optimization": ["01_deterministic_baseline.md", "02_hard_constraints.md"],
    "simulation": ["01_deterministic_baseline.md", "03_statistical_rigor.md"],
    "multiobjective": ["04_pareto_vs_weighted.md"],
    "general": ["05_source_traceability.md"],
}

SOURCE_SKILL = "0.0.15 mma-paper/mma-review/mma-figure/metaheuristic"
SOURCE_VERSION = "0.0.15"


def list_guides() -> list[str]:
    return sorted(p.name for p in GUIDE_DIR.glob("*.md"))


def load_guide(name: str) -> str:
    p = GUIDE_DIR / name
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def get_guides_for_profile(profile: str) -> list[dict[str, Any]]:
    """Return guides for a diagnostic profile with hash and provenance."""
    files = _GUIDE_MAP.get(profile, []) + _GUIDE_MAP.get("general", [])
    # Dedupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    result = []
    for fname in ordered:
        content = load_guide(fname)
        if not content:
            continue
        result.append(
            {
                "name": fname,
                "content": content,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "source_skill": SOURCE_SKILL,
                "source_version": SOURCE_VERSION,
            }
        )
    return result


def get_all_guides_manifest() -> dict[str, Any]:
    guides = []
    for fname in list_guides():
        content = load_guide(fname)
        guides.append(
            {
                "name": fname,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "chars": len(content),
            }
        )
    return {"source_skill": SOURCE_SKILL, "source_version": SOURCE_VERSION, "guides": guides}
