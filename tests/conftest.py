import pytest
from typing import Any, ContextManager
from types import TracebackType

from bullet.testclient import TestClient
from tests.types import TestClientFactory
from bullet import BulletApp
import functools


@pytest.fixture
def app():
    app = BulletApp()
    return app


@pytest.fixture
def test_client_factory(app: BulletApp) -> TestClientFactory:
    # anyio_backend_name defined by:
    # https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on
    return functools.partial(
        TestClient,
        app=app,
    )
