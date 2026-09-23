"""Guard rail: the MVP contains no broker order-write capability anywhere in the code base."""

from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import REPO_ROOT
from trading_core.harness import FORBIDDEN_TOOL_NAME_FRAGMENTS, ToolSpec

FORBIDDEN_PATTERNS = [
    re.compile(r"\b(place|submit|send|create|modify|amend|replace|cancel)_?order\w*\s*\(", re.I),
    re.compile(r"\border_?(submit|submission|entry|execution)\b", re.I),
    re.compile(r"\b(buy|sell)_?market\s*\(", re.I),
    re.compile(r"paper_?trad(e|ing)_?(api|client|order)", re.I),
]

SCAN_ROOTS = [
    REPO_ROOT / "packages",
    REPO_ROOT / "services",
    REPO_ROOT / "apps" / "web" / "src",
    REPO_ROOT / "supabase",
]
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".sql"}
EXCLUDED_PARTS = {"node_modules", ".venv", "__pycache__", "dist"}


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if path.suffix in SCAN_SUFFIXES and not EXCLUDED_PARTS & set(path.parts):
                files.append(path)
    return files


def test_no_order_write_code_paths() -> None:
    offenders: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}: {match.group(0)}")
    assert offenders == [], "broker order-write code is forbidden in the MVP"


def test_tool_spec_name_fragments_are_blocklisted() -> None:
    assert {"order", "shell", "exec", "http_request"} <= FORBIDDEN_TOOL_NAME_FRAGMENTS
    spec = ToolSpec(
        name="get_bars",
        description="Return completed bars for an instrument.",
        parameters={"type": "object", "properties": {}},
        version="1.0.0",
    )
    assert not any(fragment in spec.name for fragment in FORBIDDEN_TOOL_NAME_FRAGMENTS)
