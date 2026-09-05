class LedgerError(Exception):
    """Base for every rule the ledger refuses to break."""


class AccountAlreadyExists(LedgerError):
    pass


class UnknownAccount(LedgerError):
    pass


class SelfTransfer(LedgerError):
    pass
