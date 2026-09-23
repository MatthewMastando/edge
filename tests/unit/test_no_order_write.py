"""Guard rail: the MVP contains no broker order-write capability anywhere in the code base."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.conftest import REPO_ROOT
from trading_core.harness import FORBIDDEN_TOOL_NAME_PATTERN, ToolSpec, is_forbidden_tool_name

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


def test_tool_names_block_broker_writes_and_allow_order_blocks() -> None:
    allowed = ("get_bars", "order_block", "get_order_blocks", "detect_fvg")
    forbidden = (
        "submit_order",
        "cancel_order",
        "place_order",
        "modify_order",
        "run_shell",
        "http_request",
        "execute",
        "paper_trade",
    )
    assert all(not is_forbidden_tool_name(name) for name in allowed)
    assert all(is_forbidden_tool_name(name) for name in forbidden)
    sql = (REPO_ROOT / "supabase/migrations/20260923000400_jobs_and_runs.sql").read_text()
    assert FORBIDDEN_TOOL_NAME_PATTERN in sql
    ToolSpec(
        name="order_block",
        description="Detect order blocks on completed bars.",
        parameters={"type": "object", "properties": {}},
        version="1.0.0",
    )
    with pytest.raises(ValidationError):
        ToolSpec(
            name="submit_order",
            description="Must not exist.",
            parameters={"type": "object", "properties": {}},
            version="1.0.0",
        )
