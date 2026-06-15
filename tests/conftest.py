import functools
from typing import Generator, TYPE_CHECKING, Any

import pytest
from msgspec import Struct

from bullet import BulletApp, Path, Request

if TYPE_CHECKING:
    from bullet import Response
from bullet.testclient import TestClient
from tests.types import TestClientFactory


class AgePath(Struct):
    age: int


@pytest.fixture
def app() -> BulletApp:
    app = BulletApp()

    async def index_page(request: Request) -> "Response[Any]":
        return 200, {"name": "loki", "age": 37}

    async def param_page(request: Request, path: Path[AgePath]) -> "Response[Any]":
        return 200, {"age": path.age}

    app.add_handler("/", index_page)
    app.add_handler("/age/<age>", param_page)
    return app


@pytest.fixture
def test_client_factory() -> TestClientFactory:
    return functools.partial(TestClient)


@pytest.fixture
def client(
    app: BulletApp, test_client_factory: TestClientFactory
) -> Generator[TestClient, None, None]:
    with test_client_factory(app) as client:
        yield client
