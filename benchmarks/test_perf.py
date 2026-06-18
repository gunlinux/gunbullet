"""In-process performance microbenchmarks for gunbullet.

These drive ``await app(scope, receive, send)`` directly -- no uvicorn, no
sockets, no httpx -- so they measure only the framework's own hot path:
routing, path-param coercion, ``Request`` construction and ``msgspec`` encoding.

Each measurement also includes a constant ``asyncio.Runner.run`` scheduling
baseline. That baseline is identical across runs, so before/after comparisons on
the same machine stay meaningful (see ``make bench`` / --benchmark-compare).
"""

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from msgspec import Struct

from gunbullet import GunbulletApp, Request

if TYPE_CHECKING:
    from gunbullet import Response


class UserResponse(Struct):
    name: str
    age: int


def _build_app() -> GunbulletApp:
    app = GunbulletApp()

    @app.route("/")
    async def index(_: Request) -> "Response[UserResponse]":
        return 200, UserResponse(name="loki", age=37)

    @app.route("/dict")
    async def index_dict(_: Request) -> "Response[dict]":
        return 200, {"name": "loki", "age": 37}

    @app.route("/age/<age>")
    async def age(_: Request, age: int) -> "Response[UserResponse]":
        return 200, UserResponse(name="loki", age=age)

    return app


def _scope(path: str, method: str = "GET") -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "state": {},
    }


async def _once(app: GunbulletApp, scope: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[
        str, Any
    ]:  # never awaited for GET; here for completeness
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    await app(scope, receive, send)
    return sent


@pytest.fixture(scope="module")
def runner() -> Any:
    with asyncio.Runner() as r:
        yield r


@pytest.fixture(scope="module")
def app() -> GunbulletApp:
    return _build_app()


def test_static_route_struct(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


def test_static_route_dict(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/dict")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


def test_dynamic_route_param(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/age/37")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


def test_not_found(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/nope")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 404
