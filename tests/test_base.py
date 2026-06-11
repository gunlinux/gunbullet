from typing import Generator
from bullet.testclient import TestClient
from tests.types import TestClientFactory

import pytest


@pytest.fixture
def client(app, test_client_factory: TestClientFactory) -> Generator[TestClient, None, None]:
    with test_client_factory(app) as client:
        yield client


def test_url_path_for(client: TestClient) -> None:
    assert client.url_path_for("func_homepage") == "/func"


def test_func_route(client: TestClient) -> None:
    response = client.get("/func")
    assert response.status_code == 200
    assert response.text == "Hello, world!"

    response = client.head("/func")
    assert response.status_code == 200
    assert response.text == ""
