import asyncio

import pytest

from vessel.application.settlement import SettlementWorker
from vessel.domain.ledger import Ledger
from vessel.domain.transfer import TransferStatus

PAYER = "acc-payer"
PAYEE = "acc-payee"


async def wait_until(predicate, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition was never met")
        await asyncio.sleep(0.001)


class SpyLedger:
    def __init__(self, pending: int) -> None:
        self.pending = pending
        self.limits: list[int | None] = []

    def settle(self, limit: int | None = None) -> int:
        self.limits.append(limit)
        taken = self.pending if limit is None else min(limit, self.pending)
        self.pending -= taken
        return taken


@pytest.fixture
def ledger() -> Ledger:
    ledger = Ledger()
    ledger.open_account(PAYER, 100_000)
    ledger.open_account(PAYEE, 0)
    return ledger


@pytest.fixture
async def worker(ledger: Ledger):
    worker = SettlementWorker(ledger, batch_size=8, idle_delay=0.001)
    yield worker
    await worker.stop()


def submit(ledger: Ledger, amount: int, key: str):
    return ledger.submit(PAYER, PAYEE, amount, key)[0]


class TestBeforeStart:
    async def test_leave_transfers_pending(
        self, ledger: Ledger, worker: SettlementWorker
    ) -> None:
        transfer = submit(ledger, 1_000, "key-1")

        await asyncio.sleep(0.01)

        assert transfer.status is TransferStatus.PENDING
        assert ledger.statement(PAYEE).balance == 0


class TestRunning:
    async def test_settle_what_was_already_pending(
        self, ledger: Ledger, worker: SettlementWorker
    ) -> None:
        transfer = submit(ledger, 1_000, "key-1")

        await worker.start()

        await wait_until(lambda: transfer.status is TransferStatus.COMPLETED)
        assert ledger.statement(PAYEE).balance == 1_000

    async def test_keep_settling_after_going_idle(
        self, ledger: Ledger, worker: SettlementWorker
    ) -> None:
        await worker.start()
        await asyncio.sleep(0.02)

        late = submit(ledger, 2_000, "key-late")

        await wait_until(lambda: late.status is TransferStatus.COMPLETED)

    async def test_mark_underfunded_transfers_as_failed(
        self, ledger: Ledger, worker: SettlementWorker
    ) -> None:
        broke = submit(ledger, 1_000_000, "key-broke")

        await worker.start()

        await wait_until(lambda: broke.status is TransferStatus.FAILED)
        assert ledger.statement(PAYER).balance == 100_000

    async def test_preserve_arrival_order_across_batches(
        self, worker: SettlementWorker
    ) -> None:
        ledger = Ledger()
        ledger.open_account(PAYER, 3_000)
        ledger.open_account(PAYEE, 0)
        transfers = [
            ledger.submit(PAYER, PAYEE, 500, f"key-{i}")[0] for i in range(150)
        ]
        ordered = SettlementWorker(ledger, batch_size=8, idle_delay=0.001)

        await ordered.start()
        await wait_until(
            lambda: all(t.status is not TransferStatus.PENDING for t in transfers)
        )
        await ordered.stop()

        completed = [t for t in transfers if t.status is TransferStatus.COMPLETED]
        assert completed == transfers[:6]


class TestBatching:
    async def test_never_ask_for_an_unbounded_drain(self) -> None:
        spy = SpyLedger(pending=10)
        worker = SettlementWorker(spy, batch_size=4, idle_delay=0.001)

        await worker.start()
        await wait_until(lambda: spy.pending == 0)
        await worker.stop()

        assert spy.limits[:3] == [4, 4, 4]
        assert None not in spy.limits


class TestStop:
    async def test_drain_what_is_left(self, ledger: Ledger) -> None:
        worker = SettlementWorker(ledger, batch_size=8, idle_delay=1.0)
        transfers = [submit(ledger, 100, f"key-{i}") for i in range(20)]

        await worker.stop()

        assert all(t.status is TransferStatus.COMPLETED for t in transfers)
        assert ledger.statement(PAYEE).balance == 2_000

    async def test_be_safe_without_a_start(self, worker: SettlementWorker) -> None:
        await worker.stop()

    async def test_be_safe_twice(self, worker: SettlementWorker) -> None:
        await worker.start()
        await worker.stop()
        await worker.stop()
