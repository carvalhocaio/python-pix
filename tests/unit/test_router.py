import pytest

from vessel.infrastructure.http.router import Route, resolve

TRANSFER_ID = "9c1f8b2e-0000-4000-8000-000000000000"


class TestStaticRoutes:
    @pytest.mark.parametrize(
        ("method", "path", "expected"),
        [
            ("GET", "/health", Route.HEALTH),
            ("POST", "/accounts", Route.CREATE_ACCOUNT),
            ("POST", "/transfers", Route.CREATE_TRANSFER),
        ],
    )
    def test_resolve_without_a_parameter(
        self, method: str, path: str, expected: Route
    ) -> None:
        assert resolve(method, path) == (expected, "")

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/health"),
            ("GET", "/accounts"),
            ("DELETE", "/accounts"),
            ("GET", "/transfers"),
            ("PUT", "/transfers"),
        ],
    )
    def test_reject_the_wrong_method(self, method: str, path: str) -> None:
        assert resolve(method, path) == (Route.METHOD_NOT_ALLOWED, "")


class TestParameterisedRoutes:
    def test_extract_a_transfer_id(self) -> None:
        assert resolve("GET", f"/transfers/{TRANSFER_ID}") == (
            Route.GET_TRANSFER,
            TRANSFER_ID,
        )

    def test_extract_an_account_id(self) -> None:
        assert resolve("GET", "/accounts/acc-1/statement") == (
            Route.STATEMENT,
            "acc-1",
        )

    def test_extract_an_account_id_that_looks_like_the_suffix(self) -> None:
        assert resolve("GET", "/accounts/statement/statement") == (
            Route.STATEMENT,
            "statement",
        )

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_reject_the_wrong_method_on_a_transfer(self, method: str) -> None:
        assert resolve(method, f"/transfers/{TRANSFER_ID}") == (
            Route.METHOD_NOT_ALLOWED,
            "",
        )

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_reject_the_wrong_method_on_a_statement(self, method: str) -> None:
        assert resolve(method, "/accounts/acc-1/statement") == (
            Route.METHOD_NOT_ALLOWED,
            "",
        )


class TestUnknownPaths:
    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("", id="empty"),
            pytest.param("/", id="root"),
            pytest.param("/unknown", id="unknown"),
            pytest.param("/health/", id="health-trailing-slash"),
            pytest.param("/transfers/", id="transfer-without-id"),
            pytest.param("/transfers/abc/extra", id="transfer-with-extra-segment"),
            pytest.param("/accounts/acc-1", id="account-without-statement"),
            pytest.param("/accounts//statement", id="statement-without-id"),
            pytest.param("/accounts/a/b/statement", id="statement-with-extra-segment"),
            pytest.param("/accounts/acc-1/statement/", id="statement-trailing-slash"),
            pytest.param("/statement", id="bare-suffix"),
        ],
    )
    def test_are_not_found(self, path: str) -> None:
        assert resolve("GET", path) == (Route.NOT_FOUND, "")
