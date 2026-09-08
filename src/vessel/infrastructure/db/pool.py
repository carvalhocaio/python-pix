from collections.abc import Sequence

import asyncpg

from vessel.domain.transfer import Transfer

DEFAULT_MIN_SIZE = 1
DEFAULT_MAX_SIZE = 2
DEFAULT_COMMAND_TIMEOUT = 5.0

SAVE_BALANCES = """
INSERT INTO accounts (id, balance, updated_at)
SELECT id, balance, NOW()
  FROM unnest($1::varchar[], $2::bigint[]) AS t(id, balance)
    ON CONFLICT (id) DO UPDATE
   SET balance = EXCLUDED.balance, updated_at = NOW()
"""

SAVE_TRANSFERS = """
INSERT INTO transfers (
    id, payer_id, payee_id, amount,
    idempotency_key, status, failure_reason, created_at, processed_at
)
SELECT id::uuid, payer_id, payee_id, amount,
       idempotency_key, status, failure_reason, created_at::timestamptz, NOW()
  FROM unnest(
    $1::text[], $2::varchar[], $3::varchar[], $4::bigint[],
    $5::varchar[], $6::varchar[], $7::text[], $8::text[]
  ) AS t(id, payer_id, payee_id, amount,
         idempotency_key, status, failure_reason, created_at)
    ON CONFLICT DO NOTHING
"""


class Database:
    __slots__ = ("_dsn", "_max_size", "_min_size", "_pool")

    def __init__(
        self,
        dsn: str,
        min_size: int = DEFAULT_MIN_SIZE,
        max_size: int = DEFAULT_MAX_SIZE,
    ) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def open(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=DEFAULT_COMMAND_TIMEOUT,
        )

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close()

    async def save_balances(self, balances: Sequence[tuple[str, int]]) -> None:
        if self._pool is None:
            raise RuntimeError("Database pool is not open")
        await self._pool.execute(
            SAVE_BALANCES,
            [account_id for account_id, _ in balances],
            [balance for _, balance in balances],
        )

    async def save_transfers(self, transfers: Sequence[Transfer]) -> None:
        if self._pool is None:
            raise RuntimeError("Database pool is not open")
        await self._pool.execute(
            SAVE_TRANSFERS,
            [t.id for t in transfers],
            [t.payer_id for t in transfers],
            [t.payee_id for t in transfers],
            [t.amount for t in transfers],
            [t.idempotency_key for t in transfers],
            [t.status for t in transfers],
            [t.failure_reason for t in transfers],
            [t.created_at for t in transfers],
        )
