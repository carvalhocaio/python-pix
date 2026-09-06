import pytest
from httpx import ASGITransport, AsyncClient

from vessel.domain.ledger import Ledger
from vessel.infrastructure.http.app import create_app

PAYER = "acc-payer"
PAYEE = "acc-payee"
MISSING_ID = "00000000-0000-4000-8000-000000000000"


def transfer_body(
    amount: int = 2_500,
    key: str = "key-1",
    payer: str = PAYER,
    payee: str = PAYEE,
) -> dict:
    return {
        "payerId": payer,
        "payeeId": payee,
        "amount": amount,
        "idempotencyKey": key,
    }


@pytest.fixture
def ledger() -> Ledger:
    ledger = Ledger()
    ledger.open_account(PAYER, 100_000)
    ledger.open_account(PAYEE, 0)
    return ledger


@pytest.fixture
async def client(ledger: Ledger):
    transport = ASGITransport(app=create_app(ledger))
    async with AsyncClient(transport=transport, base_url="http://vessel") as client:
        yield client


class TestHealth:
    async def test_report_ok(self, client: AsyncClient) -> None:
        response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_answer_json(self, client: AsyncClient) -> None:
        response = await client.get("/health")

        assert response.headers["content-type"] == "application/json"


class TestCreateAccount:
    async def test_return_the_created_account(self, client: AsyncClient) -> None:
        response = await client.post(
            "/accounts", json={"id": "acc-new", "balance": 5_000}
        )

        assert response.status_code == 201
        assert response.json() == {"id": "acc-new", "balance": 5_000}

    async def test_make_the_account_usable(self, client: AsyncClient) -> None:
        await client.post("/accounts", json={"id": "acc-new", "balance": 5_000})

        response = await client.get("/accounts/acc-new/statement")

        assert response.status_code == 200
        assert response.json()["balance"] == 5_000

    async def test_reject_a_duplicate(self, client: AsyncClient) -> None:
        response = await client.post("/accounts", json={"id": PAYER, "balance": 1})

        assert response.status_code == 409

    async def test_leave_the_original_untouched_on_conflict(
        self, client: AsyncClient
    ) -> None:
        await client.post("/accounts", json={"id": PAYER, "balance": 1})

        response = await client.get(f"/accounts/{PAYER}/statement")

        assert response.json()["balance"] == 100_000

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"balance": 100}, id="missing-id"),
            pytest.param({"id": "", "balance": 100}, id="empty-id"),
            pytest.param({"id": "acc-x"}, id="missing-balance"),
            pytest.param({"id": "acc-x", "balance": -1}, id="negative-balance"),
            pytest.param({"id": "acc-x", "balance": 10.5}, id="fractional-balance"),
        ],
    )
    async def test_reject_an_invalid_payload(
        self, client: AsyncClient, body: dict
    ) -> None:
        response = await client.post("/accounts", json=body)

        assert response.status_code == 422

    async def test_reject_malformed_json(self, client: AsyncClient) -> None:
        response = await client.post(
            "/accounts",
            content=b'{"id": ',
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 422


class TestCreateTransfer:
    async def test_be_born_pending_without_moving_money(
        self, client: AsyncClient, ledger: Ledger
    ) -> None:
        response = await client.post("/transfers", json=transfer_body())
        body = response.json()

        assert response.status_code == 201
        assert body["id"]
        assert body["status"] == "pending"
        assert body["failureReason"] is None
        assert body["amount"] == 2_500
        assert body["idempotencyKey"] == "key-1"
        assert ledger.statement(PAYER).balance == 100_000

    async def test_accept_an_amount_beyond_the_balance(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/transfers", json=transfer_body(amount=1_000_000))

        assert response.status_code == 201
        assert response.json()["status"] == "pending"

    @pytest.mark.parametrize(
        ("payer", "payee"),
        [
            pytest.param("acc-ghost", PAYEE, id="unknown-payer"),
            pytest.param(PAYER, "acc-ghost", id="unknown-payee"),
            pytest.param(PAYER, PAYER, id="self-transfer"),
        ],
    )
    async def test_reject_a_broken_relationship(
        self, client: AsyncClient, payer: str, payee: str
    ) -> None:
        response = await client.post(
            "/transfers", json=transfer_body(payer=payer, payee=payee)
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "amount",
        [
            pytest.param(0, id="zero"),
            pytest.param(-1, id="negative"),
            pytest.param(10.5, id="fractional"),
        ],
    )
    async def test_reject_a_bad_amount(
        self, client: AsyncClient, amount: float
    ) -> None:
        response = await client.post("/transfers", json=transfer_body(amount=amount))

        assert response.status_code == 422

    async def test_reject_a_missing_field(self, client: AsyncClient) -> None:
        body = transfer_body()
        del body["idempotencyKey"]

        response = await client.post("/transfers", json=body)

        assert response.status_code == 422


class TestIdempotency:
    async def test_replay_the_original_transfer(self, client: AsyncClient) -> None:
        first = await client.post("/transfers", json=transfer_body())
        second = await client.post("/transfers", json=transfer_body(amount=9_999))

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json() == first.json()

    async def test_debit_only_once(self, client: AsyncClient, ledger: Ledger) -> None:
        for _ in range(10):
            await client.post("/transfers", json=transfer_body())
        ledger.settle()

        assert ledger.statement(PAYER).balance == 97_500
        assert ledger.statement(PAYEE).balance == 2_500


class TestGetTransfer:
    async def test_reflect_a_settled_transfer(
        self, client: AsyncClient, ledger: Ledger
    ) -> None:
        created = (await client.post("/transfers", json=transfer_body())).json()
        ledger.settle()

        response = await client.get(f"/transfers/{created['id']}")

        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    async def test_report_the_failure_reason(
        self, client: AsyncClient, ledger: Ledger
    ) -> None:
        created = (
            await client.post("/transfers", json=transfer_body(amount=1_000_000))
        ).json()
        ledger.settle()

        body = (await client.get(f"/transfers/{created['id']}")).json()

        assert body["status"] == "failed"
        assert body["failureReason"] == "insufficient_funds"

    async def test_be_not_found_when_unknown(self, client: AsyncClient) -> None:
        response = await client.get(f"/transfers/{MISSING_ID}")

        assert response.status_code == 404


class TestStatement:
    async def test_start_empty(self, client: AsyncClient) -> None:
        response = await client.get(f"/accounts/{PAYER}/statement")

        assert response.status_code == 200
        assert response.json() == {
            "accountId": PAYER,
            "balance": 100_000,
            "transfers": [],
        }

    async def test_list_completed_transfers_newest_first(
        self, client: AsyncClient, ledger: Ledger
    ) -> None:
        created = [
            (
                await client.post(
                    "/transfers", json=transfer_body(amount=1_000, key=f"key-{i}")
                )
            ).json()["id"]
            for i in range(3)
        ]
        ledger.settle()

        body = (await client.get(f"/accounts/{PAYER}/statement")).json()

        assert body["balance"] == 97_000
        assert [t["id"] for t in body["transfers"]] == created[::-1]
        assert all(t["status"] == "completed" for t in body["transfers"])

    async def test_hide_pending_and_failed(
        self, client: AsyncClient, ledger: Ledger
    ) -> None:
        await client.post(
            "/transfers", json=transfer_body(amount=1_000_000, key="broke")
        )
        ledger.settle()
        await client.post("/transfers", json=transfer_body(amount=1_000, key="waiting"))

        body = (await client.get(f"/accounts/{PAYER}/statement")).json()

        assert body["transfers"] == []
        assert body["balance"] == 100_000

    async def test_reach_both_sides(self, client: AsyncClient, ledger: Ledger) -> None:
        await client.post("/transfers", json=transfer_body(amount=1_000))
        ledger.settle()

        payee_body = (await client.get(f"/accounts/{PAYEE}/statement")).json()

        assert payee_body["balance"] == 1_000
        assert len(payee_body["transfers"]) == 1

    async def test_be_not_found_when_unknown(self, client: AsyncClient) -> None:
        response = await client.get("/accounts/acc-ghost/statement")

        assert response.status_code == 404


class TestRouting:
    async def test_unknown_path_is_not_found(self, client: AsyncClient) -> None:
        response = await client.get("/nope")

        assert response.status_code == 404

    async def test_wrong_method_is_not_allowed(self, client: AsyncClient) -> None:
        response = await client.get("/transfers")

        assert response.status_code == 405


class TestLifespan:
    async def test_complete_startup_and_shutdown(self, ledger: Ledger) -> None:
        app = create_app(ledger)
        events = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
        sent: list[str] = []

        async def receive() -> dict:
            return next(events)

        async def send(message: dict) -> None:
            sent.append(message["type"])

        await app({"type": "lifespan"}, receive, send)

        assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
