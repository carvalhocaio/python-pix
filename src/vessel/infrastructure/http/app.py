from collections.abc import Awaitable, Callable

import msgspec

from vessel.domain.errors import AccountAlreadyExists, SelfTransfer, UnknownAccount
from vessel.domain.ledger import Ledger
from vessel.infrastructure.http.router import Route, resolve
from vessel.infrastructure.http.schemas import decode_account, decode_transfer, encode

Message = dict
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
Response = tuple[Message, Message]

_CONTENT_TYPE = (b"content-type", b"application/json")


def _canned(status: int, body: bytes) -> Response:
    return (
        {
            "type": "http.response.start",
            "status": status,
            "headers": [_CONTENT_TYPE, (b"content-length", b"%d" % len(body))],
        },
        {"type": "http.response.body", "body": body},
    )


_HEALTH = _canned(200, b'{"status":"ok"}')
_NOT_FOUND = _canned(404, b'{"error":"not_found"}')
_NOT_ALLOWED = _canned(405, b'{"error":"method_not_allowed"}')
_CONFLICT = _canned(409, b'{"error":"conflict"}')
_UNPROCESSABLE = _canned(422, b'{"error":"unprocessable_entity"}')


async def _reply(send: Send, response: Response) -> None:
    await send(response[0])
    await send(response[1])


async def _reply_json(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [_CONTENT_TYPE, (b"content-length", b"%d" % len(body))],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive: Receive) -> bytes:
    message = await receive()
    body = message.get("body", b"")
    if not message.get("more_body", False):
        return body

    chunks = [body]
    while message.get("more_body", False):
        message = await receive()
        chunks.append(message.get("body", b""))
    return b"".join(chunks)


async def _create_transfer(ledger: Ledger, receive: Receive, send: Send) -> None:
    try:
        payload = decode_transfer(await _read_body(receive))
        transfer, created = ledger.submit(
            payload.payer_id,
            payload.payee_id,
            payload.amount,
            payload.idempotency_key,
        )
    except msgspec.DecodeError, UnknownAccount, SelfTransfer:
        await _reply(send, _UNPROCESSABLE)
        return

    await _reply_json(send, 201 if created else 200, encode(transfer))


async def _create_account(ledger: Ledger, receive: Receive, send: Send) -> None:
    try:
        payload = decode_account(await _read_body(receive))
    except msgspec.DecodeError:
        await _reply(send, _UNPROCESSABLE)
        return

    try:
        ledger.open_account(payload.id, payload.balance)
    except AccountAlreadyExists:
        await _reply(send, _CONFLICT)
        return

    await _reply_json(send, 201, encode(payload))


async def _lifespan(receive: Receive, send: Send) -> None:
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


def create_app(ledger: Ledger) -> Callable[[Message, Receive, Send], Awaitable[None]]:
    statement_of = ledger.statement
    transfer_by_id = ledger.find_transfer

    async def app(scope: Message, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await _lifespan(receive, send)
            return

        route, param = resolve(scope["method"], scope["path"])

        if route is Route.CREATE_TRANSFER:
            await _create_transfer(ledger, receive, send)
        elif route is Route.STATEMENT:
            statement = statement_of(param)
            if statement is None:
                await _reply(send, _NOT_FOUND)
            else:
                await _reply_json(send, 200, encode(statement))
        elif route is Route.GET_TRANSFER:
            transfer = transfer_by_id(param)
            if transfer is None:
                await _reply(send, _NOT_FOUND)
            else:
                await _reply_json(send, 200, encode(transfer))
        elif route is Route.CREATE_ACCOUNT:
            await _create_account(ledger, receive, send)
        elif route is Route.HEALTH:
            await _reply(send, _HEALTH)
        elif route is Route.METHOD_NOT_ALLOWED:
            await _reply(send, _NOT_ALLOWED)
        else:
            await _reply(send, _NOT_FOUND)

    return app
