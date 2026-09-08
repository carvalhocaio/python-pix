import asyncio
from collections import deque

import pytest

from vessel.domain.transfer import Transfer, TransferStatus
from vessel.infrastructure.db.writer import PersistenceWorker


def transfer(tag: str) -> Transfer:
    return Transfer(
        id=f"id-{tag}",
        payer_id="acc-a",
        payee_id="acc-b",
        amount=100,
        idempotency_key=f"key-{tag}",
        status=TransferStatus.COMPLETED,
        failure_reason=None,
        created_at="2026-07-24T12:00:00.000000+00:00",
    )


class FakeJournal:
    def __init__(self, transfers=(), balances=()) -> None:
        self.transfers = deque(transfers)
        self.balances = list(balances)
        self.settled_drains = 0

    def drain_settled(self, limit: int) -> list[Transfer]:
        self.settled_drains += 1
        taken = min(limit, len(self.transfers))
        popleft = self.transfers.popleft
        return [popleft() for _ in range(taken)]

    def drain_dirty_balances(self) -> list[tuple[str, int]]:
        drained, self.balances = self.balances, []
        return drained


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []
        self.balances_fail = False
        self.transfers_fail = False

    async def save_balances(self, balances) -> None:
        if self.balances_fail:
            raise RuntimeError("balances unavailable")
        self.calls.append(("balances", list(balances)))

    async def save_transfers(self, transfers) -> None:
        if self.transfers_fail:
            raise RuntimeError("transfers unavailable")
        self.calls.append(("transfers", list(transfers)))


async def wait_until(predicate, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition was never met")
        await asyncio.sleep(0.001)


def kinds(store: FakeStore) -> list[str]:
    return [kind for kind, _ in store.calls]


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


class TestFlushOrder:
    async def test_write_accounts_before_transfers(self, store: FakeStore) -> None:
        journal = FakeJournal([transfer("1")], [("acc-a", 900)])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=0.001)

        await worker.start()
        await wait_until(lambda: kinds(store) == ["balances", "transfers"])
        await worker.stop()

    async def test_hold_transfers_back_when_accounts_fail(
        self, store: FakeStore
    ) -> None:
        store.balances_fail = True
        journal = FakeJournal([transfer("1")], [("acc-a", 900)])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=0.001)

        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

        assert store.calls == []

    async def test_skip_the_account_write_when_nothing_changed(
        self, store: FakeStore
    ) -> None:
        journal = FakeJournal([transfer("1")], [])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=0.001)

        await worker.start()
        await wait_until(lambda: kinds(store) == ["transfers"])
        await worker.stop()


class TestFailureHandling:
    async def test_keep_a_rejected_batch_and_retry_it(self, store: FakeStore) -> None:
        store.transfers_fail = True
        journal = FakeJournal([transfer("1"), transfer("2")], [])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=0.001)

        await worker.start()
        await asyncio.sleep(0.03)
        store.transfers_fail = False
        await wait_until(lambda: kinds(store) == ["transfers"])
        await worker.stop()

        assert [t.id for t in store.calls[0][1]] == ["id-1", "id-2"]

    async def test_not_drain_more_while_holding_a_rejected_batch(
        self, store: FakeStore
    ) -> None:
        store.transfers_fail = True
        journal = FakeJournal([transfer("1")], [])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=0.001)

        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

        assert journal.settled_drains == 1

    async def test_survive_a_failure_and_keep_running(self, store: FakeStore) -> None:
        store.transfers_fail = True
        journal = FakeJournal([transfer("1")], [])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=0.001)

        await worker.start()
        await asyncio.sleep(0.03)
        store.transfers_fail = False
        journal.balances.append(("acc-a", 500))

        await wait_until(lambda: kinds(store) == ["balances", "transfers"])
        await worker.stop()


class TestBatching:
    async def test_honour_the_batch_size(self, store: FakeStore) -> None:
        journal = FakeJournal([transfer(str(i)) for i in range(25)], [])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=0.001)

        await worker.start()
        await wait_until(lambda: len(store.calls) == 3)
        await worker.stop()

        assert [len(batch) for _, batch in store.calls] == [10, 10, 5]

    async def test_stay_quiet_when_there_is_nothing_to_write(
        self, store: FakeStore
    ) -> None:
        worker = PersistenceWorker(FakeJournal(), store, idle_delay=0.001)

        await worker.start()
        await asyncio.sleep(0.03)
        await worker.stop()

        assert store.calls == []


class TestStop:
    async def test_flush_what_is_left(self, store: FakeStore) -> None:
        journal = FakeJournal([transfer("1")], [("acc-a", 900)])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=10.0)

        await worker.stop()

        assert kinds(store) == ["balances", "transfers"]

    async def test_be_safe_twice(self, store: FakeStore) -> None:
        worker = PersistenceWorker(FakeJournal(), store, idle_delay=0.001)

        await worker.start()
        await worker.stop()
        await worker.stop()

    async def test_flush_more_than_one_batch(self, store: FakeStore) -> None:
        journal = FakeJournal([transfer(str(i)) for i in range(25)], [])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=10.0)

        await worker.stop()

        assert [len(batch) for _, batch in store.calls] == [10, 10, 5]

    async def test_stop_early_when_the_store_is_down(self, store: FakeStore) -> None:
        store.transfers_fail = True
        journal = FakeJournal([transfer(str(i)) for i in range(25)], [])
        worker = PersistenceWorker(journal, store, batch_size=10, idle_delay=10.0)

        await worker.stop()

        assert store.calls == []
        assert journal.settled_drains == 1
