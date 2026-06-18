# NOTE

Смысл этого проекта, на работе и не только я перепогружался в тонкости работы asgi/wsgi/aiohttp/rsgi и granian.
И вдруг понял, что в целом понимаю как работает вся эта машинерия и мне стало интересно смогу ли я сделать yet another one web framework.

Это не серебреная пуля - это просто проект, на покекать

Дизайн:

- [x] Простота
- [x] Скорость
- [x] Микрофреймворк


# Gunbullet

A small async web micro-framework built directly on the raw ASGI protocol.
No Flask, Django, or FastAPI under the hood — Gunbullet implements routing,
request parsing, parameter extraction, validation, and a test client by hand.
[`msgspec`](https://jcristharif.com/msgspec/) is the only
serialization/validation dependency.

- **Python 3.13+**
- Managed with [`uv`](https://docs.astral.sh/uv/)
- ASGI app — runs under any ASGI server (uvicorn, hypercorn, …)

---

## Install & run

```bash
uv sync --dev                       # install deps (incl. linters, pytest)
make test                           # run the test suite
make check                          # lint + fix + types + test
```

See the [Quickstart](#quickstart) below for writing an app against the
framework. A runnable example app lives in the separate `gunbullet_example`
repo.

---

## Quickstart

A Gunbullet app is an ASGI callable. Create one, register handlers, and hand it
to an ASGI server.

```python
# app/__init__.py
from msgspec import Struct
from gunbullet import GunbulletApp, Request


class UserResponse(Struct):
    name: str
    age: int


def create_app_asgi() -> GunbulletApp:
    app = GunbulletApp()

    @app.get("/")
    async def index(request: Request) -> UserResponse:
        return UserResponse(name="loki", age=37)

    return app
```

```python
# main.py
from app import create_app_asgi

app_asgi = create_app_asgi()
```

```bash
uv run uvicorn main:app_asgi
```

---

## Handlers

A handler is an `async def` that:

- takes `request: Request` as its **first** argument,
- returns a **body** (`str`, `dict`, or `msgspec.Struct`) — defaulting to
  **200** — or an explicit **`(status, body)`** tuple to set the status code.

Every return value is JSON-encoded with
`Content-Type: application/json; charset=utf-8`. `400`, `404`, and `405` are
still produced by the framework on bad input / routing.

```python
@app.get("/ping")
async def ping(request: Request) -> dict:
    return {"pong": True}                 # 200

@app.post("/items")
async def create(request: Request) -> dict:
    return 201, {"created": True}         # explicit status
```

### Typed returns: `Response` and `HandlerReturn`

Two type aliases (importable from `gunbullet`) annotate what a handler returns:

- `Response[T]` — the `(status, body)` tuple form, `tuple[int, T]`.
- `HandlerReturn[T]` — either form, `Response[T] | T`. Use this when the handler
  returns a **bare body** (defaulting to 200) so the annotation matches the
  value the type checker sees.

```python
from gunbullet import Response, HandlerReturn

@app.get("/")
async def index(request: Request) -> HandlerReturn[Greeting]:
    return Greeting(...)                  # bare body -> 200

@app.get("/items/<item_id>")
async def get_item(request: Request, item_id: int) -> Response[Item]:
    return 200, item                      # explicit (status, body)
```

---

## Routing

Register routes with the decorators or with `add_handler`.

```python
@app.route("/items")                # all methods (default)
async def items(request: Request) -> dict: ...

# equivalent imperative form:
async def items(request: Request) -> dict: ...
app.add_handler("/items", items)
```

### HTTP method dispatch

`route` / `add_handler` accept a `methods=` list. A route registered **without**
`methods=` answers **all** verbs (a catch-all). Per-verb shortcut decorators are
provided:

```python
@app.get("/users")
async def list_users(request: Request) -> dict: ...

@app.post("/users")
async def create_user(request: Request) -> dict: ...

@app.route("/health", methods=["GET", "HEAD"])
async def health(request: Request) -> dict: ...
```

Shortcuts: `@app.get`, `@app.post`, `@app.put`, `@app.patch`, `@app.delete`.

The same path may hold several handlers, one per method group. Dispatch:

- path + matching method → the handler runs (**200**)
- path matches but **no** registered method allows the verb → **405**
  `{"error": "Method not allowed"}`
- no path matches → **404** `{"error": "Not found"}`

### Static vs dynamic routes

- **Static** routes (no `<param>`) are stored in a dict for O(1) lookup.
- **Dynamic** routes (`/users/<id>`) are matched by compiled regex in
  registration order. Each `<name>` segment matches one path segment
  (`[^/]+`).

---

## Path, query, and body parameters

Handlers declare where each argument comes from via `Annotated` markers, or by
naming a route parameter directly. All extraction uses `msgspec`, so values are
validated and coerced. Any validation/decoding error during extraction returns
**400** `{"error": ...}`.

Markers are imported from `gunbullet`:

```python
from gunbullet import Query, Body, Path
```

### Bare path params

A plain typed argument whose name matches a `<route_param>` is coerced directly
— no marker struct needed.

```python
@app.get("/age/<age>")
async def show_age(request: Request, age: int) -> dict:
    return {"age": age}          # GET /age/37 -> {"age": 37}
                                 # GET /age/foo -> 400
```

### `Path[Struct]` — group path params into a struct

`Path[...]` requires a `msgspec.Struct`; its fields are filled from the route
parameters.

```python
from msgspec import Struct

class UserPath(Struct):
    user_id: int

@app.get("/users/<user_id>")
async def get_user(request: Request, path: Path[UserPath]) -> dict:
    return {"id": path.user_id}
```

### `Query[Struct]` — parse the query string

The query string is converted into the struct with lenient coercion.

```python
class Filters(Struct):
    limit: int = 20
    q: str = ""

@app.get("/search")
async def search(request: Request, filters: Query[Filters]) -> dict:
    return {"limit": filters.limit, "q": filters.q}
    # GET /search?q=cats&limit=5 -> {"limit": 5, "q": "cats"}
```

### `Body[Struct]` — decode the JSON request body

```python
class NewUser(Struct):
    name: str
    age: int

@app.post("/users")
async def create_user(request: Request, body: Body[NewUser]) -> dict:
    return {"created": body.name, "age": body.age}
```

### Registration-time validation

When a handler is registered, Gunbullet checks that every `<route_param>` in the
path is covered by a handler argument or a `Path` struct field. If not, it
raises `ValueError` **at registration time** (fail-fast), not on request:

```python
@app.get("/users/<user_id>")
async def bad(request: Request) -> dict:   # user_id is never consumed
    return {}
# ValueError: route params not covered by any Path[...] struct: user_id
```

---

## The `Request` object

Passed as the first argument to every handler. The `scope` is parsed lazily and
cached.

| Attribute / method        | Description                                              |
| ------------------------- | ------------------------------------------------------- |
| `request.method`          | Uppercased HTTP method (`"GET"`, `"POST"`, …)           |
| `request.path`            | Request path                                            |
| `request.body`            | Raw request body (`bytes`)                              |
| `request.headers`         | Case-insensitive `Headers` mapping (`.get`, `[]`, `in`) |
| `request.query`           | `dict[str, str]` of query params (first value per key)  |
| `request.cookies`         | `dict[str, str]` parsed from the `Cookie` header        |
| `request.json(type=dict)` | Decode the body via `msgspec`, optionally into a struct |
| `request.state`           | Per-request view of the lifespan state dict             |
| `request.app`             | The owning `GunbulletApp` (e.g. `request.app.state`)       |

```python
@app.get("/whoami")
async def whoami(request: Request) -> dict:
    return {
        "ua": request.headers.get("user-agent"),
        "session": request.cookies.get("session"),
    }
```

---

## Lifespan (startup & shutdown)

Register startup/shutdown logic FastAPI-style with `@app.lifespan`. The function
runs startup code, `yield`s once, then runs shutdown code. An optional dict
yielded at the `yield` is merged into the ASGI scope state and surfaces on
`request.state`.

```python
@app.lifespan
async def lifespan(app):
    pool = await connect()       # startup
    yield {"db": pool}           # state -> request.state["db"]
    await pool.close()           # shutdown


@app.get("/items")
async def items(request: Request) -> dict:
    db = request.state["db"]
    return {"items": await db.fetch_all()}
```

A plain async generator is auto-wrapped with
`contextlib.asynccontextmanager`; an already-wrapped CM factory is accepted
as-is. You can also pass it to the constructor:

```python
app = GunbulletApp(lifespan=lifespan)
```

If startup raises, Gunbullet reports `lifespan.startup.failed` with the exception
message and the server does not start.

---

## Application state

`app.state` is an attribute-access namespace for objects that live for the whole
application (clients, config, …), reachable from handlers via
`request.app.state`.

```python
app.state.config = load_config()

@app.get("/version")
async def version(request: Request) -> dict:
    return {"version": request.app.state.config.version}
```

> `request.state` is per-request data populated by the **lifespan** (the dict
> you `yield`); `request.app.state` is the long-lived **application** namespace.

---

## Exception handlers

A handler can raise a plain domain exception and let a registered handler turn
it into an HTTP response, keeping status-code plumbing out of the handlers
themselves. Register one with `add_exception_handler(ExcType, handler)`; the
handler takes `(request, exc)` and returns a body or `(status, body)` tuple like
any other handler.

```python
class ItemNotFound(Exception):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} does not exist")
        self.item_id = item_id


async def handle_not_found(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, ItemNotFound)
    return 404, {"error": "not_found", "item_id": exc.item_id}


@app.get("/items/<item_id>")
async def get_item(request: Request, item_id: int) -> Response[Item]:
    item = request.state["items"].get(item_id)
    if item is None:
        raise ItemNotFound(item_id)       # -> handle_not_found -> 404
    return 200, item

app.add_exception_handler(ItemNotFound, handle_not_found)
```

Dispatch matches the raised exception's **exact type** (`type(exc)`), not
subclasses. A raised exception with no registered handler is **not** swallowed:
under ASGI it propagates to the server's fallback, and under RSGI the framework
emits `500 {"error": "Internal server error"}` (see the RSGI caveats below).

---

## Running under Granian (RSGI)

Besides the ASGI interface, the same `GunbulletApp` runs directly on Granian's
[RSGI](https://github.com/emmett-framework/granian) interface — Granian's Rust
core reads the socket and assembles the whole request body itself, so there is
no per-chunk `receive()` loop and the response goes out in a single
`response_bytes` call.

```bash
uv run granian --interface rsgi main:app_asgi --workers 1 --no-ws
```

The same app object is served by both interfaces: ASGI calls `__call__`, RSGI
calls `__rsgi__`. Handlers, routing, params, and `request.*` behave identically.

### Known caveats / differences vs. ASGI

These are RSGI-specific behaviors to be aware of:

- **`request.state` is shared, not per-request.** RSGI has no per-request scope
  state, so the dict yielded by the lifespan is surfaced on `request.state`
  **as the same object** for every request in the worker. Under ASGI each
  request gets a shallow copy, so mutating `request.state` in a handler is
  isolated; under RSGI a write leaks to all other requests. Treat
  `request.state` as **read-only** under RSGI, or use `request.app.state` for
  intentionally app-wide data.
- **HTTP only.** WebSocket (`ws`) scopes are ignored — Granian is started with
  `--no-ws` above. Non-HTTP scopes get no response.
- **Unhandled handler exceptions return 500.** When a handler raises and no
  exception handler is registered, the ASGI path leaves the server's own
  fallback to answer; under RSGI the app emits an explicit `500
  {"error": "Internal server error"}` because Granian has no such fallback and
  would otherwise leave the connection hanging.
- **Lifespan runs via sync hooks.** RSGI has no ASGI-style lifespan protocol;
  Granian calls `__rsgi_init__` / `__rsgi_del__` with the event loop before and
  after serving, and the framework drives the async lifespan context manager on
  that loop. A failing startup propagates and aborts the worker (matching ASGI's
  fail-fast), and shutdown is skipped if startup never completed.

## Testing

`gunbullet.testclient.TestClient` is a **synchronous** client (built on `httpx` +
`anyio`) that drives the app in-process — no network. It subclasses
`httpx.Client`, so it exposes `.get`, `.post`, `.put`, `.patch`, `.delete`, etc.

```python
from gunbullet.testclient import TestClient

def test_index(app):
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"name": "loki", "age": 37}
```

Using it as a **context manager** (`with TestClient(app) as client:`) runs the
app's lifespan startup/shutdown around the block, so `request.state` is
populated. Without the context manager the lifespan does not run.

```python
def test_method_dispatch(app):
    with TestClient(app) as client:
        assert client.post("/users").status_code == 200
        assert client.put("/users").status_code == 405      # method not allowed
        assert client.get("/nope").status_code == 404        # no such route
```

Run the suite:

```bash
make test                           # pytest
uv run pytest tests/test_methods.py # a single file
```

---

## Project layout

```
main.py            entry point: app_asgi = create_app_asgi()  (served by uvicorn)
app/__init__.py    create_app_asgi() — wires up a GunbulletApp with example routes
gunbullet/            the framework
  app.py           GunbulletApp — the ASGI callable, routing, lifespan
  _routing.py      Handler + registration-time validation
  _http.py         Request, Headers, State
  params.py        Query / Body / Path markers
  testclient.py    synchronous in-process TestClient
tests/             pytest suite driving the app through TestClient
```

---

## Commands

```bash
uv sync --dev      # install deps
make dev           # sync dev deps
make check         # lint + fix + types + test  (run before finishing)
make lint          # ruff check
make fix           # ruff check --fix && ruff format
make types         # pyright
make test          # pytest
```

---

## Roadmap

Not implemented yet (responses are JSON-only):

- Custom response **headers** from handlers (status codes are supported via the
  `(status, body)` tuple form).
- Repeated query values (`?tag=a&tag=b` keeps only the first today).
- Middleware, typed path converters (`<int:id>`), and non-JSON responses.
