import uvicorn

from vessel.application.settlement import SettlementWorker
from vessel.config import load
from vessel.domain.ledger import Ledger
from vessel.infrastructure.http.app import create_app


def main() -> None:
    config = load()
    ledger = Ledger()
    worker = SettlementWorker(ledger, config.batch_size, config.idle_delay)
    app = create_app(
        ledger,
        on_startup=(worker.start,),
        on_shutdown=(worker.stop,),
    )

    uvicorn.run(
        app,
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
