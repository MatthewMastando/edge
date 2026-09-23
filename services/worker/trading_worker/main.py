"""Worker entrypoint.

Stage 0 ships the process skeleton: settings, signal handling, a poll loop and the handler
registry contract. Stage 1B implements lease acquisition (``select ... for update skip locked``),
checkpointed workflow stages and the state-machine updates against ``public.jobs``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from typing import TYPE_CHECKING, Protocol

from trading_worker import __version__
from trading_worker.settings import WorkerSettings, get_settings

if TYPE_CHECKING:
    from trading_core.domain.jobs import Job, JobKind

log = logging.getLogger("trading_worker")


class JobHandler(Protocol):
    """Runs one job kind. Implementations must be idempotent per ``job.idempotency_key`` and
    resume from ``job.checkpoint``."""

    @property
    def kind(self) -> JobKind: ...

    async def run(self, job: Job) -> None: ...


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, handler: JobHandler) -> None:
        if handler.kind in self._handlers:
            msg = f"handler already registered for {handler.kind}"
            raise ValueError(msg)
        self._handlers[handler.kind] = handler

    def get(self, kind: str) -> JobHandler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers)


class Worker:
    def __init__(self, settings: WorkerSettings, registry: HandlerRegistry) -> None:
        self._settings = settings
        self._registry = registry
        self._stop = asyncio.Event()
        self.iterations = 0

    def request_stop(self) -> None:
        self._stop.set()

    async def poll_once(self) -> int:
        """Lease and run available jobs. Returns the number of jobs processed (0 in Stage 0)."""
        self.iterations += 1
        if not self._registry.kinds():
            log.debug("no handlers registered; idle")
        return 0

    async def run(self, *, once: bool = False) -> None:
        log.info(
            "trading-worker %s starting (id=%s, mode=%s, handlers=%s)",
            __version__,
            self._settings.effective_worker_id,
            self._settings.mode,
            self._registry.kinds() or "none",
        )
        while not self._stop.is_set():
            processed = await self.poll_once()
            if once:
                break
            if processed == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._settings.poll_interval_seconds
                    )
        log.info("trading-worker stopped after %d poll(s)", self.iterations)


def build_registry() -> HandlerRegistry:
    """Stage 1B registers research/ta_scan/snapshot handlers here."""
    return HandlerRegistry()


async def _amain(once: bool) -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    worker = Worker(settings, build_registry())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)
    await worker.run(once=once)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-worker")
    parser.add_argument("--once", action="store_true", help="poll a single time and exit")
    args = parser.parse_args(argv)
    asyncio.run(_amain(once=bool(args.once)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
