"""In-process performance microbenchmarks for gunbullet.

These drive ``await app(scope, receive, send)`` directly -- no uvicorn, no
sockets, no httpx -- so they measure only the framework's own hot path:
routing, path-param coercion, ``Request`` construction, request-body decoding
and ``msgspec`` encoding.

Each measurement also includes a constant ``asyncio.Runner.run`` scheduling
baseline. That baseline is identical across runs, so before/after comparisons on
the same machine stay meaningful (see ``make bench`` / --benchmark-compare).

The cases are deliberately spread across cheap and expensive shapes:

* tiny static/dynamic responses -- the framework overhead floor;
* big nested / list responses -- the ``msgspec.json.encode`` hot path;
* ``dict`` vs ``Struct`` payloads -- typed encoding vs the slower, fully
  introspected ``dict`` path (the "worst serialization path");
* POST bodies -- the ``receive()`` body loop plus ``msgspec.json.decode``
  validation, including a large decode+re-encode round trip;
* ``Query[...]`` / ``Path[...]`` struct coercion via ``msgspec.convert``;
* a crowded router where the matching dynamic route is scanned last.
"""

import asyncio
from typing import TYPE_CHECKING, Any

import msgspec
import pytest
from msgspec import Struct

from gunbullet import Body, GunbulletApp, Path, Query, Request

if TYPE_CHECKING:
    from gunbullet import Response

# Size of the "bigger model" collections. 100 rows is a realistic page of a
# list endpoint and large enough that encode/decode dominates the per-call
# framework overhead.
BIG_N = 100
# Number of dynamic routes registered before the one we actually hit, so the
# linear scan in ``GunbulletApp._dynamic`` is exercised at its worst case.
CROWDED_ROUTES = 50


class UserResponse(Struct):
    name: str
    age: int


class Address(Struct):
    street: str
    city: str
    zip: str
    country: str


class Profile(Struct):
    """A realistically shaped, nested API model."""

    id: int
    name: str
    age: int
    email: str
    active: bool
    address: Address
    tags: list[str]


class UserList(Struct):
    users: list[Profile]
    total: int


class SearchQuery(Struct):
    q: str
    page: int = 1
    limit: int = 20


class UserPath(Struct):
    org: str
    user_id: int


def _make_profile(i: int) -> Profile:
    return Profile(
        id=i,
        name=f"user-{i}",
        age=20 + (i % 50),
        email=f"user{i}@example.com",
        active=i % 2 == 0,
        address=Address(
            street=f"{i} Main St",
            city="Springfield",
            zip=f"{10000 + i}",
            country="US",
        ),
        tags=[f"tag-{i}", "active", "beta"],
    )


# Pre-built payloads. Constructing/encoding these is *not* part of any
# measurement -- the benchmarks reuse these constants so only the server path
# (decode/route/encode) is timed.
_PROFILES = [_make_profile(i) for i in range(BIG_N)]
_USER_LIST = UserList(users=_PROFILES, total=BIG_N)
_PROFILE_DICTS = [msgspec.to_builtins(p) for p in _PROFILES]

_PROFILE_BODY = msgspec.json.encode(_make_profile(1))
_USER_LIST_BODY = msgspec.json.encode(_USER_LIST)

_JSON_HEADERS = [(b"content-type", b"application/json")]


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

    # --- bigger / nested responses (encode hot path) ---
    @app.route("/profile")
    async def profile(_: Request) -> "Response[Profile]":
        return 200, _make_profile(1)

    @app.get("/users")
    async def users(_: Request) -> "Response[UserList]":
        return 200, _USER_LIST

    # The "worst serialization path": a large list of plain ``dict``s, which
    # msgspec must fully introspect at encode time rather than using a known
    # Struct layout.
    @app.route("/users-dict")
    async def users_dict(_: Request) -> "Response[dict]":
        return 200, {"users": _PROFILE_DICTS, "total": BIG_N}

    # --- request bodies (receive loop + decode validation) ---
    @app.post("/users")
    async def create_user(_: Request, profile: Body[Profile]) -> "Response[Profile]":
        return 200, profile

    @app.post("/users/bulk")
    async def create_users(_: Request, payload: Body[UserList]) -> "Response[UserList]":
        return 200, payload

    # --- query / path struct coercion via msgspec.convert ---
    @app.route("/search")
    async def search(_: Request, params: Query[SearchQuery]) -> "Response[dict]":
        return 200, {"q": params.q, "page": params.page, "limit": params.limit}

    @app.route("/org/<org>/user/<user_id>")
    async def org_user(_: Request, loc: Path[UserPath]) -> "Response[dict]":
        return 200, {"org": loc.org, "user_id": loc.user_id}

    return app


def _build_crowded_app() -> GunbulletApp:
    """An app with many dynamic routes; the target route is registered last."""
    app = GunbulletApp()

    for i in range(CROWDED_ROUTES):

        @app.route(f"/res{i}/<rid>")
        async def _decoy(_: Request, rid: int) -> "Response[dict]":
            return 200, {"rid": rid}

    @app.route("/target/<rid>")
    async def target(_: Request, rid: int) -> "Response[dict]":
        return 200, {"rid": rid}

    return app


def _scope(
    path: str,
    method: str = "GET",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers if headers is not None else [],
        "query_string": query_string,
        "state": {},
    }


async def _once(
    app: GunbulletApp, scope: dict[str, Any], body: bytes = b""
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:  # only awaited for bodyful methods
        return {"type": "http.request", "body": body, "more_body": False}

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


@pytest.fixture(scope="module")
def crowded_app() -> GunbulletApp:
    return _build_crowded_app()


# --- baseline / tiny responses ------------------------------------------------


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


def test_method_not_allowed(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    # /users/bulk is POST-only, so a GET matches the path but no method.
    scope = _scope("/users/bulk", method="GET")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 405


# --- bigger / nested responses (encode hot path) -----------------------------


def test_nested_struct(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/profile")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


def test_large_struct_list(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/users")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


def test_large_dict_list(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    # Worst serialization path: a big list of untyped dicts.
    scope = _scope("/users-dict")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


# --- request bodies (receive loop + decode validation) -----------------------


def test_post_body_struct(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/users", method="POST", headers=_JSON_HEADERS)
    sent = benchmark(lambda: runner.run(_once(app, scope, _PROFILE_BODY)))
    assert sent[0]["status"] == 200


def test_post_large_body(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    # Worst round-trip: decode a big body into structs, then re-encode it.
    scope = _scope("/users/bulk", method="POST", headers=_JSON_HEADERS)
    sent = benchmark(lambda: runner.run(_once(app, scope, _USER_LIST_BODY)))
    assert sent[0]["status"] == 200


# --- query / path struct coercion --------------------------------------------


def test_query_struct(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/search", query_string=b"q=python&page=3&limit=50")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


def test_path_struct(benchmark: Any, app: GunbulletApp, runner: Any) -> None:
    scope = _scope("/org/acme/user/42")
    sent = benchmark(lambda: runner.run(_once(app, scope)))
    assert sent[0]["status"] == 200


# --- routing under many dynamic routes ---------------------------------------


def test_crowded_dynamic_routes(
    benchmark: Any, crowded_app: GunbulletApp, runner: Any
) -> None:
    # The matching route is registered last, so the dynamic scan is worst-case.
    scope = _scope("/target/7")
    sent = benchmark(lambda: runner.run(_once(crowded_app, scope)))
    assert sent[0]["status"] == 200
