from collections import deque
from datetime import UTC, datetime
from uuid import uuid4

from vessel.domain.errors import AccountAlreadyExists, SelfTransfer, UnknownAccount
from vessel.domain.transfer import FailureReason, Statement, Transfer, TransferStatus


class Ledger:
    __slots__ = ("_balances", "_by_key", "_history", "_pending", "_transfers")

    def __init__(self) -> None:
        self._balances: dict[str, int] = {}
        self._transfers: dict[str, Transfer] = {}
        self._by_key: dict[str, Transfer] = {}
        self._history: dict[str, list[Transfer]] = {}
        self._pending: deque[Transfer] = deque()

    def open_account(self, account_id: str, balance: int) -> None:
        if account_id in self._balances:
            raise AccountAlreadyExists
        self._balances[account_id] = balance
        self._history[account_id] = []

    def submit(
        self,
        payer_id: str,
        payee_id: str,
        amount: int,
        idempotency_key: str,
    ) -> tuple[Transfer, bool]:
        known = self._by_key.get(idempotency_key)
        if known is not None:
            return known, False

        balances = self._balances
        if payer_id not in balances or payee_id not in balances:
            raise UnknownAccount
        if payer_id == payee_id:
            raise SelfTransfer

        transfer = Transfer(
            id=str(uuid4()),
            payer_id=payer_id,
            payee_id=payee_id,
            amount=amount,
            idempotency_key=idempotency_key,
            status=TransferStatus.PENDING,
            failure_reason=None,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._by_key[idempotency_key] = transfer
        self._transfers[transfer.id] = transfer
        self._pending.append(transfer)
        return transfer, True

    def settle(self, limit: int | None = None) -> int:
        pending = self._pending
        balances = self._balances
        history = self._history

        budget = len(pending)
        if limit is not None and limit < budget:
            budget = limit

        for _ in range(budget):
            transfer = pending.popleft()
            payer_id = transfer.payer_id
            payee_id = transfer.payee_id
            amount = transfer.amount
            balance = balances[payer_id]

            if balance >= amount:
                balances[payer_id] = balance - amount
                balances[payee_id] += amount
                transfer.status = TransferStatus.COMPLETED
                history[payer_id].append(transfer)
                history[payee_id].append(transfer)
            else:
                transfer.status = TransferStatus.FAILED
                transfer.failure_reason = FailureReason.INSUFFICIENT_FUNDS

        return budget

    def find_transfer(self, transfer_id: str) -> Transfer | None:
        return self._transfers.get(transfer_id)

    def statement(self, account_id: str) -> Statement | None:
        balance = self._balances.get(account_id)
        if balance is None:
            return None
        return Statement(
            account_id=account_id,
            balance=balance,
            transfers=self._history[account_id][::-1],
        )
