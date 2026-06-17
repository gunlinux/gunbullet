# NOTE

Смысл этого проекта, на работе и не только я перепогружался в тонкости работы asgi/wsgi/aiohttp/rsgi и granian.
И вдруг понял, что в целом понимаю как работает вся эта машинерия и мне стало интересно смогу ли я сделать yet another one web framework.

Это не серебреная пуля - это просто проект, на покекать

Дизайн:

- [x] Простота
- [x] Скорость
- [x] Микрофреймворк


# Bullet

A small async web micro-framework built directly on the raw ASGI protocol.
No Flask, Django, or FastAPI under the hood — Bullet implements routing,
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
uv run uvicorn main:app_asgi        # run the dev server from the repo root
make dev                            # uv sync --dev + run uvicorn
```

Always run from the repo root — imports assume that working directory.

---

## Quickstart

A Bullet app is an ASGI callable. Create one, register handlers, and hand it
to an ASGI server.

```python
# app/__init__.py
from msgspec import Struct
from bullet import BulletApp, Request


class UserResponse(Struct):
    name: str
    age: int


def create_app_asgi() -> BulletApp:
    app = BulletApp()

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
- returns a `str`, `dict`, or `msgspec.Struct`.

Every return value is JSON-encoded with
`Content-Type: application/json; charset=utf-8`. A successful handler always
yields **200**; `400`, `404`, and `405` are produced by the framework, not the
handler.

```python
@app.get("/ping")
async def ping(request: Request) -> dict:
    return {"pong": True}
```

> There is no `Response` object yet — you cannot set custom status codes or
> headers from a handler. See [Roadmap](#roadmap).

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

Markers are imported from `bullet`:

```python
from bullet import Query, Body, Path
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

When a handler is registered, Bullet checks that every `<route_param>` in the
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
| `request.app`             | The owning `BulletApp` (e.g. `request.app.state`)       |

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
app = BulletApp(lifespan=lifespan)
```

If startup raises, Bullet reports `lifespan.startup.failed` with the exception
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

## Testing

`bullet.testclient.TestClient` is a **synchronous** client (built on `httpx` +
`anyio`) that drives the app in-process — no network. It subclasses
`httpx.Client`, so it exposes `.get`, `.post`, `.put`, `.patch`, `.delete`, etc.

```python
from bullet.testclient import TestClient

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
app/__init__.py    create_app_asgi() — wires up a BulletApp with example routes
bullet/            the framework
  app.py           BulletApp — the ASGI callable, routing, lifespan
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
make dev           # sync + run uvicorn main:app_asgi
make check         # lint + fix + types + test  (run before finishing)
make lint          # ruff check
make fix           # ruff check --fix && ruff format
make types         # pyright
make test          # pytest
```

---

## Roadmap

Not implemented yet (handlers are JSON-only and always 200 on success):

- A `Response` / `HTTPException` layer — custom status codes and headers from
  handlers.
- Repeated query values (`?tag=a&tag=b` keeps only the first today).
- Middleware, typed path converters (`<int:id>`), and non-JSON responses.
