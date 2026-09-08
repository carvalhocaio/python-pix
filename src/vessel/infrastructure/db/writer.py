import asyncio
import contextlib
from collections.abc import Sequence
from typing import Protocol

from vessel.domain.transfer import Transfer

DEFAULT_BATCH_SIZE = 1000
DEFAULT_IDLE_DELAY = 0.05


class Journal(Protocol):
    def drain_settled(self, limit: int) -> list[Transfer]: ...

    def drain_dirty_balances(self) -> list[tuple[str, int]]: ...


class Store(Protocol):
    async def save_balances(self, balances: Sequence[tuple[str, int]]) -> None: ...

    async def save_transfers(self, transfers: Sequence[Transfer]) -> None: ...


class PersistenceWorker:
    __slots__ = (
        "_batch_size",
        "_held_balances",
        "_held_transfers",
        "_idle_delay",
        "_journal",
        "_running",
        "_store",
        "_task",
    )

    def __init__(
        self,
        journal: Journal,
        store: Store,
        batch_size: int = DEFAULT_BATCH_SIZE,
        idle_delay: float = DEFAULT_IDLE_DELAY,
    ) -> None:
        self._journal = journal
        self._store = store
        self._batch_size = batch_size
        self._idle_delay = idle_delay
        self._held_balances: list[tuple[str, int]] = []
        self._held_transfers: list[Transfer] = []
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

        while await self._flush():
            pass

    async def _run(self) -> None:
        while self._running:
            if await self._flush():
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(self._idle_delay)

    async def _flush(self) -> bool:
        balances = self._held_balances or self._journal.drain_dirty_balances()
        if balances:
            try:
                await self._store.save_balances(balances)
            except Exception:
                self._held_balances = balances
                return False
            self._held_balances = []

        transfers = self._held_transfers or self._journal.drain_settled(
            self._batch_size
        )
        if not transfers:
            return False

        try:
            await self._store.save_transfers(transfers)
        except Exception:
            self._held_transfers = transfers
            return False

        self._held_transfers = []
        return True
