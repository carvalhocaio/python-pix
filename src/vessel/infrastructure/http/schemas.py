from typing import Annotated

import msgspec

AccountId = Annotated[str, msgspec.Meta(min_length=1)]
IdempotencyKey = Annotated[str, msgspec.Meta(min_length=1, max_length=128)]
Balance = Annotated[int, msgspec.Meta(ge=0)]
Cents = Annotated[int, msgspec.Meta(gt=0)]


class AccountPayload(msgspec.Struct):
    id: AccountId
    balance: Balance


class TransferPayload(msgspec.Struct, rename="camel"):
    payer_id: AccountId
    payee_id: AccountId
    amount: Cents
    idempotency_key: IdempotencyKey


decode_account = msgspec.json.Decoder(AccountPayload).decode
decode_transfer = msgspec.json.Decoder(TransferPayload).decode
encode = msgspec.json.Encoder().encode
