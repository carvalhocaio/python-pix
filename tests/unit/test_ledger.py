import msgspec
import pytest

from vessel.domain.errors import AccountAlreadyExists, SelfTransfer, UnknownAccount
from vessel.domain.ledger import Ledger
from vessel.domain.transfer import FailureReason, Statement, TransferStatus

PAYER = "acc-payer"
PAYEE = "acc-payee"
GHOST = "acc-ghost"


@pytest.fixture
def ledger() -> Ledger:
    return Ledger()


@pytest.fixture
def funded(ledger: Ledger) -> Ledger:
    ledger.open_account(PAYER, 100_000)
    ledger.open_account(PAYEE, 0)
    return ledger


def submit(
    ledger: Ledger,
    amount: int,
    key: str,
    payer: str = PAYER,
    payee: str = PAYEE,
):
    return ledger.submit(payer, payee, amount, key)


def entries(statement: Statement) -> list[dict]:
    return [msgspec.json.decode(entry) for entry in reversed(statement.entries)]


class TestAccounts:
    def test_opens_with_the_given_balance(self, ledger: Ledger) -> None:
        ledger.open_account(PAYER, 100_000)

        statement = ledger.statement(PAYER)

        assert statement is not None
        assert statement.balance == 100_000
        assert statement.entries == []

    def test_rejects_a_duplicated_id(self, ledger: Ledger) -> None:
        ledger.open_account(PAYER, 1_000)

        with pytest.raises(AccountAlreadyExists):
            ledger.open_account(PAYER, 5_000)

    def test_statement_of_an_unknown_account_is_none(self, ledger: Ledger) -> None:
        assert ledger.statement(GHOST) is None


class TestSubmission:
    @pytest.mark.parametrize(
        ("payer", "payee"),
        [(GHOST, PAYEE), (PAYER, GHOST), (GHOST, GHOST)],
    )
    def test_rejects_unknown_accounts(
        self, funded: Ledger, payer: str, payee: str
    ) -> None:
        with pytest.raises(UnknownAccount):
            submit(funded, 1_000, "key-1", payer=payer, payee=payee)

    def test_rejects_a_self_transfer(self, funded: Ledger) -> None:
        with pytest.raises(SelfTransfer):
            submit(funded, 1_000, "key-1", payee=PAYER)

    def test_creates_a_pending_transfer_without_touching_balances(
        self, funded: Ledger
    ) -> None:
        transfer, created = submit(funded, 2_500, "key-1")

        assert created is True
        assert transfer.status is TransferStatus.PENDING
        assert transfer.failure_reason is None
        assert transfer.amount == 2_500
        assert funded.statement(PAYER).balance == 100_000
        assert funded.statement(PAYEE).balance == 0

    def test_accepts_an_amount_beyond_the_balance(self, funded: Ledger) -> None:
        transfer, _ = submit(funded, 1_000_000, "key-1")

        assert transfer.status is TransferStatus.PENDING

    def test_a_known_key_returns_the_original_transfer(self, funded: Ledger) -> None:
        original, _ = submit(funded, 2_500, "key-1")

        repeated, created = submit(funded, 9_999, "key-1")

        assert created is False
        assert repeated.id == original.id
        assert repeated.amount == 2_500

    def test_a_known_key_never_produces_a_second_debit(self, funded: Ledger) -> None:
        for _ in range(50):
            submit(funded, 2_500, "key-1")

        funded.settle()

        assert funded.statement(PAYER).balance == 97_500
        assert funded.statement(PAYEE).balance == 2_500


class TestSettlement:
    def test_moves_the_money_and_completes(self, funded: Ledger) -> None:
        transfer, _ = submit(funded, 2_500, "key-1")

        assert funded.settle() == 1

        assert transfer.status is TransferStatus.COMPLETED
        assert transfer.failure_reason is None
        assert funded.statement(PAYER).balance == 97_500
        assert funded.statement(PAYEE).balance == 2_500

    def test_drains_the_exact_balance(self, funded: Ledger) -> None:
        transfer, _ = submit(funded, 100_000, "key-1")
        funded.settle()

        assert transfer.status is TransferStatus.COMPLETED
        assert funded.statement(PAYER).balance == 0

    def test_fails_without_moving_money_when_funds_are_short(
        self, funded: Ledger
    ) -> None:
        transfer, _ = submit(funded, 100_001, "key-1")
        funded.settle()

        assert transfer.status is TransferStatus.FAILED
        assert transfer.failure_reason is FailureReason.INSUFFICIENT_FUNDS
        assert funded.statement(PAYER).balance == 100_000
        assert funded.statement(PAYEE).balance == 0

    def test_honours_arrival_order_when_funds_run_out(self, ledger: Ledger) -> None:
        ledger.open_account(PAYER, 3_000)
        ledger.open_account(PAYEE, 0)
        transfers = [submit(ledger, 500, f"key-{i}")[0] for i in range(150)]

        ledger.settle()

        completed = [t for t in transfers if t.status is TransferStatus.COMPLETED]
        assert completed == transfers[:6]
        assert ledger.statement(PAYER).balance == 0

    def test_stops_at_the_batch_limit(self, funded: Ledger) -> None:
        for i in range(10):
            submit(funded, 100, f"key-{i}")

        assert funded.settle(limit=4) == 4
        assert funded.statement(PAYEE).balance == 400

    def test_never_settles_a_transfer_twice(self, funded: Ledger) -> None:
        submit(funded, 500, "key-1")
        funded.settle()

        assert funded.settle() == 0
        assert funded.statement(PAYEE).balance == 500


class TestStatement:
    def test_lists_only_completed_transfers(self, ledger: Ledger) -> None:
        ledger.open_account(PAYER, 1_000)
        ledger.open_account(PAYEE, 0)
        completed, _ = submit(ledger, 1_000, "key-ok")
        submit(ledger, 5_000, "key-broke")
        ledger.settle()

        statement = ledger.statement(PAYEE)

        assert [e["id"] for e in entries(statement)] == [completed.id]

    def test_lists_both_sides_newest_first(self, funded: Ledger) -> None:
        funded.open_account("acc-third", 50_000)
        outgoing, _ = submit(funded, 3_000, "key-out")
        incoming, _ = funded.submit("acc-third", PAYER, 1_000, "key-in")
        funded.settle()

        statement = funded.statement(PAYER)

        assert [e["id"] for e in entries(statement)] == [incoming.id, outgoing.id]
        assert statement.balance == 98_000

    def test_replays_to_the_current_balance(self, funded: Ledger) -> None:
        for i in range(20):
            submit(funded, 250, f"key-{i}")
        funded.settle()

        statement = funded.statement(PAYER)
        replayed = 100_000 + sum(
            e["amount"] if e["payeeId"] == PAYER else -e["amount"]
            for e in entries(statement)
        )

        assert replayed == statement.balance


def test_conservation_holds_across_a_circular_run(ledger: Ledger) -> None:
    accounts = ["acc-a", "acc-b", "acc-c"]
    for account in accounts:
        ledger.open_account(account, 50_000)
    pairs = [("acc-a", "acc-b"), ("acc-b", "acc-c"), ("acc-c", "acc-a")]

    for i in range(300):
        payer, payee = pairs[i % len(pairs)]
        ledger.submit(payer, payee, 500, f"key-{i}")
    ledger.settle()

    balances = [ledger.statement(a).balance for a in accounts]
    assert sum(balances) == 150_000
    assert all(balance >= 0 for balance in balances)
