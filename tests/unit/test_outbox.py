import pytest

from vessel.domain.ledger import Ledger

PAYER = "acc-payer"
PAYEE = "acc-payee"


@pytest.fixture
def ledger() -> Ledger:
    return Ledger()


@pytest.fixture
def funded(ledger: Ledger) -> Ledger:
    ledger.open_account(PAYER, 100_000)
    ledger.open_account(PAYEE, 0)
    return ledger


def submit(ledger: Ledger, amount: int, key: str):
    return ledger.submit(PAYER, PAYEE, amount, key)


class TestSettledOutbox:
    def test_start_empty(self, funded: Ledger) -> None:
        assert funded.drain_settled(10) == []

    def test_ignore_transfers_that_are_still_pending(self, funded: Ledger) -> None:
        submit(funded, 2_500, "key-1")

        assert funded.drain_settled(10) == []

    def test_collect_completed_and_failed_alike(self, funded: Ledger) -> None:
        completed = submit(funded, 2_500, "key-ok")[0]
        failed = submit(funded, 1_000_000, "key-broke")[0]
        funded.settle()

        assert funded.drain_settled(10) == [completed, failed]

    def test_preserve_settlement_order(self, funded: Ledger) -> None:
        transfers = [submit(funded, 100, f"key-{i}")[0] for i in range(20)]
        funded.settle()

        assert funded.drain_settled(20) == transfers

    def test_honour_the_limit(self, funded: Ledger) -> None:
        transfers = [submit(funded, 100, f"key-{i}")[0] for i in range(10)]
        funded.settle()

        assert funded.drain_settled(4) == transfers[:4]
        assert funded.drain_settled(10) == transfers[4:]

    def test_hand_each_transfer_over_once(self, funded: Ledger) -> None:
        submit(funded, 100, "key-1")
        funded.settle()
        funded.drain_settled(10)

        assert funded.drain_settled(10) == []


class TestDirtyBalances:
    def test_flag_a_new_account(self, ledger: Ledger) -> None:
        ledger.open_account(PAYER, 100_000)

        assert dict(ledger.drain_dirty_balances()) == {PAYER: 100_000}

    def test_flag_both_sides_of_a_settlement(self, funded: Ledger) -> None:
        funded.drain_dirty_balances()
        submit(funded, 2_500, "key-1")
        funded.settle()

        assert dict(funded.drain_dirty_balances()) == {PAYER: 97_500, PAYEE: 2_500}

    def test_ignore_a_failed_settlement(self, funded: Ledger) -> None:
        funded.drain_dirty_balances()
        submit(funded, 1_000_000, "key-broke")
        funded.settle()

        assert funded.drain_dirty_balances() == []

    def test_coalesce_repeated_changes(self, funded: Ledger) -> None:
        funded.drain_dirty_balances()
        for i in range(50):
            submit(funded, 100, f"key-{i}")
        funded.settle()

        assert dict(funded.drain_dirty_balances()) == {PAYER: 95_000, PAYEE: 5_000}

    def test_report_the_balance_at_drain_time(self, funded: Ledger) -> None:
        funded.drain_dirty_balances()
        submit(funded, 2_500, "key-1")
        funded.settle()
        submit(funded, 1_500, "key-2")
        funded.settle()

        assert dict(funded.drain_dirty_balances()) == {PAYER: 96_000, PAYEE: 4_000}

    def test_clear_after_draining(self, funded: Ledger) -> None:
        funded.drain_dirty_balances()

        assert funded.drain_dirty_balances() == []
