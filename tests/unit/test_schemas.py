import msgspec
import pytest

from vessel.domain.transfer import FailureReason, Statement, Transfer, TransferStatus
from vessel.infrastructure.http.schemas import (
    AccountPayload,
    TransferPayload,
    decode_account,
    decode_transfer,
    encode,
)

VALID_TRANSFER = (
    b'{"payerId": "acc-1", "payeeId": "acc-2", '
    b'"amount": 2500, "idempotencyKey": "abc-123"}'
)


def transfer(
    status: TransferStatus = TransferStatus.PENDING,
    failure_reason: FailureReason | None = None,
) -> Transfer:
    return Transfer(
        id="9c1f8b2e-0000-4000-8000-000000000000",
        payer_id="acc-1",
        payee_id="acc-2",
        amount=2500,
        idempotency_key="abc-123",
        status=status,
        failure_reason=failure_reason,
        created_at="2026-07-24T12:00:00+00:00",
    )


class TestAccountPayload:
    def test_decodes_a_valid_payload(self) -> None:
        decoded = decode_account(b'{"id": "acc-1", "balance": 100000}')

        assert decoded == AccountPayload(id="acc-1", balance=100_000)

    def test_accepts_a_zero_balance(self) -> None:
        assert decode_account(b'{"id": "acc-1", "balance": 0}').balance == 0

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(b'{"balance": 100}', id="missing-id"),
            pytest.param(b'{"id": "", "balance": 100}', id="empty-id"),
            pytest.param(b'{"id": null, "balance": 100}', id="null-id"),
            pytest.param(b'{"id": "acc-1"}', id="missing-balance"),
            pytest.param(b'{"id": "acc-1", "balance": -1}', id="negative-balance"),
            pytest.param(b'{"id": "acc-1", "balance": 10.5}', id="fractional-balance"),
            pytest.param(
                b'{"id": "acc-1", "balance": 100.0}', id="whole-float-balance"
            ),
            pytest.param(b'{"id": "acc-1", "balance": "100"}', id="balance-as-text"),
        ],
    )
    def test_rejects_invalid_payloads(self, body: bytes) -> None:
        with pytest.raises(msgspec.ValidationError):
            decode_account(body)

    def test_rejects_malformed_json(self) -> None:
        with pytest.raises(msgspec.DecodeError):
            decode_account(b'{"id": ')


class TestTransferPayload:
    def test_decodes_camel_case_into_snake_case_fields(self) -> None:
        decoded = decode_transfer(VALID_TRANSFER)

        assert decoded == TransferPayload(
            payer_id="acc-1",
            payee_id="acc-2",
            amount=2500,
            idempotency_key="abc-123",
        )

    def test_rejects_snake_case_keys(self) -> None:
        body = (
            b'{"payer_id": "acc-1", "payee_id": "acc-2", '
            b'"amount": 2500, "idempotency_key": "abc-123"}'
        )

        with pytest.raises(msgspec.ValidationError):
            decode_transfer(body)

    @pytest.mark.parametrize(
        "amount",
        [b"0", b"-1", b"-5000", b"10.5", b"2500.0", b'"2500"', b"null"],
    )
    def test_rejects_a_non_positive_or_non_integer_amount(self, amount: bytes) -> None:
        body = (
            b'{"payerId": "acc-1", "payeeId": "acc-2", '
            b'"amount": ' + amount + b', "idempotencyKey": "abc-123"}'
        )

        with pytest.raises(msgspec.ValidationError):
            decode_transfer(body)

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                b'{"payeeId": "acc-2", "amount": 2500, "idempotencyKey": "k"}',
                id="missing-payer",
            ),
            pytest.param(
                b'{"payerId": "acc-1", "amount": 2500, "idempotencyKey": "k"}',
                id="missing-payee",
            ),
            pytest.param(
                b'{"payerId": "acc-1", "payeeId": "acc-2", "idempotencyKey": "k"}',
                id="missing-amount",
            ),
            pytest.param(
                b'{"payerId": "acc-1", "payeeId": "acc-2", "amount": 2500}',
                id="missing-key",
            ),
            pytest.param(
                b'{"payerId": "", "payeeId": "acc-2", '
                b'"amount": 2500, "idempotencyKey": "k"}',
                id="empty-payer",
            ),
        ],
    )
    def test_rejects_invalid_payloads(self, body: bytes) -> None:
        with pytest.raises(msgspec.ValidationError):
            decode_transfer(body)


class TestEncoding:
    def test_encodes_a_transfer_in_camel_case(self) -> None:
        assert msgspec.json.decode(encode(transfer())) == {
            "id": "9c1f8b2e-0000-4000-8000-000000000000",
            "payerId": "acc-1",
            "payeeId": "acc-2",
            "amount": 2500,
            "idempotencyKey": "abc-123",
            "status": "pending",
            "failureReason": None,
            "createdAt": "2026-07-24T12:00:00+00:00",
        }

    def test_encodes_enums_as_plain_text(self) -> None:
        failed = transfer(TransferStatus.FAILED, FailureReason.INSUFFICIENT_FUNDS)

        encoded = msgspec.json.decode(encode(failed))

        assert encoded["status"] == "failed"
        assert encoded["failureReason"] == "insufficient_funds"

    def test_encodes_a_statement_in_camel_case(self) -> None:
        statement = Statement(
            account_id="acc-1", balance=97_500, transfers=[transfer()]
        )

        encoded = msgspec.json.decode(encode(statement))

        assert encoded["accountId"] == "acc-1"
        assert encoded["balance"] == 97_500
        assert [t["id"] for t in encoded["transfers"]] == [transfer().id]

    def test_encodes_an_account_payload_as_the_created_resource(self) -> None:
        payload = AccountPayload(id="acc-1", balance=1_000)

        assert msgspec.json.decode(encode(payload)) == {"id": "acc-1", "balance": 1_000}
