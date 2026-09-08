import sys
from collections.abc import Awaitable, Callable

import uvicorn

from vessel.application.settlement import SettlementWorker
from vessel.config import Config, load
from vessel.domain.ledger import Ledger
from vessel.infrastructure.db.pool import Database
from vessel.infrastructure.db.writer import PersistenceWorker
from vessel.infrastructure.http.app import create_app

NO_DATABASE_WARNING = "vessel: DATABASE_URL is unset, running without persistence"


def build_app(config: Config, ledger: Ledger) -> Callable[..., Awaitable[None]]:
    settlement = SettlementWorker(ledger, config.batch_size, config.idle_delay)

    if config.database_url is None:
        print(NO_DATABASE_WARNING, file=sys.stderr)
        return create_app(ledger, (settlement.start,), (settlement.stop,))

    database = Database(config.database_url)
    persistence = PersistenceWorker(
        ledger, database, config.write_batch_size, config.write_delay
    )

    return create_app(
        ledger,
        on_startup=(database.open, settlement.start, persistence.start),
        on_shutdown=(settlement.stop, persistence.stop, database.close),
    )


def main() -> None:
    config = load()

    uvicorn.run(
        build_app(config, Ledger()),
        host=config.host,
        port=config.port,
        loop="uvloop",
        http="httptools",
        lifespan="on",
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
