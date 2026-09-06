import asyncio
import contextlib
from typing import Protocol

DEFAULT_BATCH_SIZE = 512
DEFAULT_IDLE_DELAY = 0.001


class Settleable(Protocol):
    def settle(self, limit: int | None = None) -> int: ...


class SettlementWorker:
    __slots__ = ("_batch_size", "_idle_delay", "_ledger", "_running", "_task")

    def __init__(
        self,
        ledger: Settleable,
        batch_size: int = DEFAULT_BATCH_SIZE,
        idle_delay: float = DEFAULT_IDLE_DELAY,
    ) -> None:
        self._ledger = ledger
        self._batch_size = batch_size
        self._idle_delay = idle_delay
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None

        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._drain()

    def _drain(self) -> None:
        settle = self._ledger.settle
        batch_size = self._batch_size
        while settle(batch_size):
            pass

    async def _run(self) -> None:
        settle = self._ledger.settle
        batch_size = self._batch_size
        idle_delay = self._idle_delay

        while self._running:
            if settle(batch_size):
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(idle_delay)
