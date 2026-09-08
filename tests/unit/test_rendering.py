import msgspec
import pytest

from vessel.domain.ledger import Ledger
from vessel.domain.transfer import Transfer, TransferStatus

PAYER = "acc-payer"
PAYEE = "acc-payee"


class SpyRenderer:
    def __init__(self) -> None:
        self.seen: list[tuple[str, TransferStatus]] = []

    def __call__(self, transfer: Transfer) -> bytes:
        self.seen.append((transfer.id, transfer.status))
        return msgspec.json.encode(transfer)


@pytest.fixture
def renderer() -> SpyRenderer:
    return SpyRenderer()


@pytest.fixture
def ledger(renderer: SpyRenderer) -> Ledger:
    ledger = Ledger(render=renderer)
    ledger.open_account(PAYER, 100_000)
    ledger.open_account(PAYEE, 0)
    return ledger


def submit(ledger: Ledger, amount: int, key: str) -> Transfer:
    return ledger.submit(PAYER, PAYEE, amount, key)[0]


class TestWhenTransfersAreRendered:
    def test_wait_for_settlement(self, ledger: Ledger, renderer: SpyRenderer) -> None:
        submit(ledger, 2_500, "key-1")

        assert renderer.seen == []

    def test_render_once_per_transfer(
        self, ledger: Ledger, renderer: SpyRenderer
    ) -> None:
        transfer = submit(ledger, 2_500, "key-1")
        ledger.settle()

        assert [seen_id for seen_id, _ in renderer.seen] == [transfer.id]

    def test_render_only_after_the_status_is_final(
        self, ledger: Ledger, renderer: SpyRenderer
    ) -> None:
        submit(ledger, 2_500, "key-1")
        ledger.settle()

        assert [status for _, status in renderer.seen] == [TransferStatus.COMPLETED]

    def test_skip_failed_transfers(
        self, ledger: Ledger, renderer: SpyRenderer
    ) -> None:
        submit(ledger, 1_000_000, "key-broke")
        ledger.settle()

        assert renderer.seen == []


class TestWhatIsStored:
    def test_share_one_rendering_between_both_sides(self, ledger: Ledger) -> None:
        submit(ledger, 2_500, "key-1")
        ledger.settle()

        payer = ledger.statement(PAYER).entries
        payee = ledger.statement(PAYEE).entries

        assert payer[0] is payee[0]

    def test_keep_the_wire_shape(self, ledger: Ledger) -> None:
        transfer = submit(ledger, 2_500, "key-1")
        ledger.settle()

        entry = msgspec.json.decode(ledger.statement(PAYER).entries[0])

        assert entry == {
            "id": transfer.id,
            "payerId": PAYER,
            "payeeId": PAYEE,
            "amount": 2_500,
            "idempotencyKey": "key-1",
            "status": "completed",
            "failureReason": None,
            "createdAt": transfer.created_at,
        }

    def test_store_entries_oldest_first(self, ledger: Ledger) -> None:
        first = submit(ledger, 100, "key-1")
        second = submit(ledger, 200, "key-2")
        ledger.settle()

        ids = [
            msgspec.json.decode(entry)["id"]
            for entry in ledger.statement(PAYER).entries
        ]

        assert ids == [first.id, second.id]
