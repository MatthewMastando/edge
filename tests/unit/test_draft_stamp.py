"""An older autosave must not replace a newer draft."""

from __future__ import annotations

from trading_api.routes.artifacts import draft_write_is_stale


def test_older_client_stamp_is_stale() -> None:
    existing = {"structured": {"clientUpdatedAt": "2026-09-23T17:00:02.000Z", "stance": "neutral"}}
    incoming = {"clientUpdatedAt": "2026-09-23T17:00:01.000Z", "stance": "neutral"}
    assert draft_write_is_stale(existing, incoming) is True


def test_newer_or_equal_stamp_is_written() -> None:
    existing = {"structured": {"clientUpdatedAt": "2026-09-23T17:00:01.000Z"}}
    same = {"clientUpdatedAt": "2026-09-23T17:00:01.000Z"}
    newer = {"clientUpdatedAt": "2026-09-23T17:00:02.000Z"}
    assert draft_write_is_stale(existing, same) is False
    assert draft_write_is_stale(existing, newer) is False


def test_missing_stamp_does_not_block_a_write() -> None:
    assert draft_write_is_stale(None, {"clientUpdatedAt": "2026-09-23T17:00:01.000Z"}) is False
    assert (
        draft_write_is_stale({"structured": {"stance": "neutral"}}, {"stance": "bearish"}) is False
    )
