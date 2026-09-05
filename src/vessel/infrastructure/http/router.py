from enum import IntEnum


class Route(IntEnum):
    CREATE_TRANSFER = 0
    STATEMENT = 1
    GET_TRANSFER = 2
    CREATE_ACCOUNT = 3
    HEALTH = 4
    NOT_FOUND = 5
    METHOD_NOT_ALLOWED = 6


_STATIC: dict[str, tuple[Route, str]] = {
    "/transfers": (Route.CREATE_TRANSFER, "POST"),
    "/accounts": (Route.CREATE_ACCOUNT, "POST"),
    "/health": (Route.HEALTH, "GET"),
}

_ACCOUNT_PREFIX = "/accounts/"
_STATEMENT_SUFFIX = "/statement"
_TRANSFER_PREFIX = "/transfers/"
_ACCOUNT_START = len(_ACCOUNT_PREFIX)
_STATEMENT_END = -len(_STATEMENT_SUFFIX)
_TRANSFER_START = len(_TRANSFER_PREFIX)

_NOT_FOUND = (Route.NOT_FOUND, "")
_METHOD_NOT_ALLOWED = (Route.METHOD_NOT_ALLOWED, "")


def resolve(method: str, path: str) -> tuple[Route, str]:  # noqa: PLR0911
    static = _STATIC.get(path)
    if static is not None:
        route, allowed = static
        return (route, "") if method == allowed else _METHOD_NOT_ALLOWED

    if path.startswith(_ACCOUNT_PREFIX):
        if path.endswith(_STATEMENT_SUFFIX):
            account_id = path[_ACCOUNT_START:_STATEMENT_END]
            if account_id and "/" not in account_id:
                if method == "GET":
                    return Route.STATEMENT, account_id
                return _METHOD_NOT_ALLOWED
        return _NOT_FOUND

    if path.startswith(_TRANSFER_PREFIX):
        transfer_id = path[_TRANSFER_START:]
        if transfer_id and "/" not in transfer_id:
            if method == "GET":
                return Route.GET_TRANSFER, transfer_id
            return _METHOD_NOT_ALLOWED
        return _NOT_FOUND

    return _NOT_FOUND
