import functools
from typing import Generator

import pytest

from bullet import BulletApp, Request
from bullet.testclient import TestClient
from tests.types import TestClientFactory


@pytest.fixture
def app() -> BulletApp:
    app = BulletApp()

    async def index_page(request: Request) -> dict:
        return {"name": "loki", "age": 37}

    async def param_page(request: Request, age: int) -> dict:
        return {"age": age}

    app.add_handler("/", index_page)
    app.add_handler("/age/<age>", param_page)
    return app


@pytest.fixture
def test_client_factory() -> TestClientFactory:
    # anyio_backend_name defined by:
    # https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on
    return functools.partial(TestClient)


@pytest.fixture
def client(
    app: BulletApp, test_client_factory: TestClientFactory
) -> Generator[TestClient, None, None]:
    with test_client_factory(app) as client:
        yield client
