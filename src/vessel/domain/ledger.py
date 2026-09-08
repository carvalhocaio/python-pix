from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import msgspec

from vessel.domain.errors import AccountAlreadyExists, SelfTransfer, UnknownAccount
from vessel.domain.transfer import FailureReason, Statement, Transfer, TransferStatus

Renderer = Callable[[Transfer], bytes]


class Ledger:
    __slots__ = (
        "_balances",
        "_by_key",
        "_dirty",
        "_history",
        "_pending",
        "_render",
        "_settled",
        "_transfers",
    )

    def __init__(self, render: Renderer = msgspec.json.encode) -> None:
        self._render = render
        self._balances: dict[str, int] = {}
        self._transfers: dict[str, Transfer] = {}
        self._by_key: dict[str, Transfer] = {}
        self._history: dict[str, list[bytes]] = {}
        self._pending: deque[Transfer] = deque()
        self._settled: deque[Transfer] = deque()
        self._dirty: set[str] = set()

    def open_account(self, account_id: str, balance: int) -> None:
        if account_id in self._balances:
            raise AccountAlreadyExists
        self._balances[account_id] = balance
        self._history[account_id] = []
        self._dirty.add(account_id)

    def submit(
        self, payer_id: str, payee_id: str, amount: int, idempotency_key: str
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
            created_at=datetime.now(UTC).isoformat(timespec="microseconds"),
        )
        self._by_key[idempotency_key] = transfer
        self._transfers[transfer.id] = transfer
        self._pending.append(transfer)
        return transfer, True

    def settle(self, limit: int | None = None) -> int:
        pending = self._pending
        balances = self._balances
        history = self._history
        settled = self._settled
        mark_dirty = self._dirty.add
        render = self._render

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
                entry = render(transfer)
                history[payer_id].append(entry)
                history[payee_id].append(entry)
                mark_dirty(payer_id)
                mark_dirty(payee_id)
            else:
                transfer.status = TransferStatus.FAILED
                transfer.failure_reason = FailureReason.INSUFFICIENT_FUNDS

            settled.append(transfer)

        return budget

    def drain_settled(self, limit: int) -> list[Transfer]:
        settled = self._settled
        count = len(settled)
        count = min(count, limit)

        popleft = settled.popleft
        return [popleft() for _ in range(count)]

    def drain_dirty_balances(self) -> list[tuple[str, int]]:
        dirty = self._dirty
        if not dirty:
            return []

        balances = self._balances
        drained = [(account_id, balances[account_id]) for account_id in dirty]
        dirty.clear()
        return drained

    def find_transfer(self, transfer_id: str) -> Transfer | None:
        return self._transfers.get(transfer_id)

    def statement(self, account_id: str) -> Statement | None:
        balance = self._balances.get(account_id)
        if balance is None:
            return None
        return Statement(
            account_id=account_id,
            balance=balance,
            entries=self._history[account_id],
        )
