from enum import StrEnum

import msgspec


class TransferStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class FailureReason(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"


class Transfer(msgspec.Struct, gc=False):
    id: str
    payer_id: str
    payee_id: str
    amount: int
    idempotency_key: str
    status: TransferStatus
    failure_reason: FailureReason | None
    created_at: str


class Statement(msgspec.Struct):
    account_id: str
    balance: int
    transfers: list[Transfer]
