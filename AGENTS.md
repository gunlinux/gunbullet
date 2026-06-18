# AGENTS.md

This file provides guidance to coding agents working in this repository.

## What this is

`gunbullet` is a learning project: a from-scratch async web micro-framework built
directly on the raw ASGI protocol (`__call__(scope, receive, send)`), with an
additional native **RSGI** entry point for [Granian](https://github.com/emmett-framework/granian).
No Flask/Django/FastAPI — the point is implementing routing, request parsing,
param extraction, validation, and a test client by hand. `msgspec` is the only
serialization/validation dependency the framework itself uses.

Routing is backed by a compiled **Rust radix-trie router** (pyo3 0.28 / maturin),
with a pure-Python fallback so the package still works from an sdist or on a
platform without a prebuilt wheel.

Python 3.13+, managed with [`uv`](https://docs.astral.sh/uv/) (`uv.lock` is
checked in). Mixed Rust/Python project built with **maturin** (`pyproject.toml`
`[build-system]`, `Cargo.toml`).

## Commands

```bash
uv sync --dev                       # install deps (incl. linters, pytest, granian, maturin)
make dev                            # uv sync --dev

make build                          # maturin develop --release: compile the Rust router into the venv
make rust-test                      # cargo test --release: native Rust router unit tests

make check                          # lint + fix + types + test  (run before finishing)
make lint                           # ruff check
make fix                            # ruff check --fix && ruff format
make types                          # pyright
make test                           # pytest (tests/ only — testpaths in pyproject.toml)
make bench                          # in-process microbenchmarks (pytest benchmarks/)

uv run pytest tests/test_params.py::test_query_decoded_with_coercion   # single test
```

Always run from the repo root — imports assume that working directory. The
compiled extension (`gunbullet/_gunbullet_router.abi3.so`) is checked in, so
plain `make test` works without a `make build` first; rebuild it with `make
build` after editing `src/lib.rs`.

## Architecture

```
gunbullet/         the framework (see below)
src/lib.rs         the Rust radix-trie router (pyo3, module gunbullet._gunbullet_router)
tests/             pytest suite driving the app through gunbullet.testclient.TestClient
benchmarks/        in-process performance microbenchmarks (make bench)
example/           a self-contained example app (in-memory CRUD); not part of the package
```

`example/main.py` exposes `app_asgi` for servers:

```bash
uv run uvicorn example.main:app_asgi
uv run granian --interface rsgi example.main:app_asgi --workers 1 --no-ws
```

### The `gunbullet` package — request lifecycle

`GunbulletApp` (`gunbullet/app.py`) is both an ASGI callable (`__call__`) and an
RSGI callable (`__rsgi__`). Both entry points share `_route` → `_resolve`; only
body reading and response sending differ. The flow when a request arrives:

1. **`gunbullet/app.py` — `GunbulletApp`.**
   - ASGI `__call__` handles the `lifespan` protocol, drains the request body
     (skipped for `_BODYLESS` methods: GET/HEAD/OPTIONS/DELETE; multi-chunk
     bodies are collected and `b"".join`ed once), then routes via `_route`.
   - RSGI `__rsgi__` (HTTP only; WebSocket scopes ignored) reads the whole body
     in a single `await protocol()` and sends in one `response_bytes` call.
   - `_route` asks the router for candidate `(params, route_id)` matches in
     priority order, picks the first whose handler `allows()` the method, and
     resolves it. Candidates but no method match → **405** `{"error": "Method
     not allowed"}`; no candidates → **404** `{"error": "Not found"}`.
   - Responses go through `_send_json` (ASGI; `bytes` header tuples, start+body
     events) or `_send_json_rsgi` (RSGI; `str` header tuples, single send), both
     encoding with `msgspec.json.encode` and setting `Content-Type:
     application/json; charset=utf-8` + `Content-Length`.

2. **Routing backend — `gunbullet/_router.py`.** Selects the backend at import:
   the compiled Rust `Router` from `gunbullet._gunbullet_router` if available,
   else the pure-Python `PyRouter` from `gunbullet/_router_py.py`. Both expose
   the same `add(pattern, route_id)` / `match(path) -> list[(params, route_id)]`
   surface — static routes first, then dynamic routes in registration order — so
   `GunbulletApp` is agnostic to which loaded. Which won is logged at INFO on
   import (set logging to INFO to confirm the Rust speedup is active). The Rust
   implementation lives in `src/lib.rs`.

3. **`gunbullet/_routing.py` — `Handler`** wraps one route + handler coroutine +
   optional allowed `methods`. At registration it inspects the handler signature
   to build extractor lists. `allows(method)` gates the method (None = all).
   `execute()` builds kwargs from the request, calls the handler, and returns the
   raw handler result. Any `msgspec.DecodeError` (which `ValidationError`
   subclasses) during extraction is caught and surfaced as **400** `{"error": ...}`.

4. **`gunbullet/params.py` — parameter markers.** Handlers declare where each arg
   comes from via `Annotated` markers:
   - `Query[MyStruct]` — query string → `msgspec.Struct` (via `msgspec.convert`,
     lenient coercion).
   - `Body[MyStruct]` — JSON request body → struct (via `msgspec.json.decode`).
   - `Path[MyStruct]` — path params → struct; **`Path[...]` requires a
     `msgspec.Struct`**, not a bare type.
   - A bare annotated param whose name matches a `<route_param>` (e.g. `item_id:
     int`) is coerced directly without a marker struct.
   - The `request: Request` first arg is always passed and skipped by all marker
     logic.

5. **`validate_handler()` (in `_routing.py`)** runs at registration time
   (`add_handler` / `@app.route` / `@app.get` / …). It raises `ValueError` if any
   `<route_param>` is not covered by a handler arg or `Path` struct field —
   fail-fast registration validation. Most "errors" in tests are
   `pytest.raises(ValueError)` at registration, not request-time failures.

6. **`gunbullet/_http.py` — `Request`** parses the ASGI `scope` lazily: `headers`
   (case-insensitive `Headers`), `query`, and `cookies` are computed on first
   access and cached. `request.json(type=...)` decodes the body via msgspec.
   `Request.from_rsgi(...)` builds an equivalent request from an RSGI scope.
   `request.state` exposes per-request state: under ASGI it's the scope `state`
   dict populated by the lifespan; under RSGI (which has no per-request scope
   state) it's the app's `_lifespan_state`. `request.app` reaches the app, and
   `request.app.state` (`State`) holds long-lived, app-wide data.

### Routing, methods, and status codes

- Register routes with `@app.route(path, methods=...)` or the verb shortcuts
  `@app.get/post/put/patch/delete`, or imperatively via `app.add_handler(route,
  handler, methods=...)`. `methods=None` allows any method.
- Handlers are `async def`, take `request: Request` first, and return a body
  (`str | dict | msgspec.Struct`, typed as `Response[T]`) **or** an explicit
  `(status, body)` tuple. `_normalize_response` defaults a bare body to status
  200; a 2-tuple `(int, body)` sets the status (e.g. `return 201, item`). 400 /
  404 / 405 / 500 are produced by the framework.

### Exception handling

`app.add_exception_handler(ExcTypeOrStatus, handler)` registers a coroutine
`handler(request, exc) -> body | (status, body)`. When a handler raises, `_resolve`
looks up the exception's exact type in `exceptions_handlers`; if found, the
exception handler's return is normalized like any response. With no registered
handler the request is left unanswered under ASGI (`None` → the server's own
fallback), while RSGI emits an explicit **500** since Granian has no such
fallback. This keeps status-code plumbing out of the handlers — they raise plain
domain errors (see `example/`'s `ItemNotFound`).

### Lifespan

`GunbulletApp` supports a FastAPI-style lifespan via the `@app.lifespan`
decorator (or the `GunbulletApp(lifespan=...)` constructor kwarg). The registered
function runs startup code, `yield`s once, then runs shutdown code; an optional
dict yielded at the `yield` is merged into per-request state and surfaces on
`request.state`:

```python
@app.lifespan
async def lifespan(app):
    pool = await connect()      # startup
    yield {"db": pool}          # state -> request.state["db"]
    await pool.close()          # shutdown
```

A plain async generator is auto-wrapped with `contextlib.asynccontextmanager`; an
already-wrapped CM factory is accepted as-is (`_as_lifespan` normalizes both).

- **ASGI**: driven by `_run_lifespan`, which enters the CM on `lifespan.startup`
  (sending `...startup.failed` with the exception message on error) and exits it
  on `lifespan.shutdown`. The yielded dict updates the scope `state`. With no
  lifespan registered it just acks the events.
- **RSGI**: Granian has no lifespan protocol, so `__rsgi_init__(loop)` /
  `__rsgi_del__(loop)` drive the same CM with `run_until_complete` before/after
  serving, and the yielded dict updates `_lifespan_state`.

### `gunbullet/testclient.py` — TestClient

A **synchronous** test client modeled on Starlette's, built on `httpx` + `anyio`.
It does not hit the network: `_ASGITransport` builds a `scope`, drives the app on
a worker event loop via an anyio blocking portal, and reassembles
`http.response.*` messages into an `httpx.Response`. As a context manager (`with
TestClient(app) as client:`) it also runs the app's `lifespan` startup/shutdown
on a persistent portal. This is the standard way the `tests/` suite exercises the
app (RSGI is covered separately in `tests/test_rsgi.py`).

## Notes

- The compiled `gunbullet/_gunbullet_router.abi3.so` is checked into the repo.
  Rebuild it with `make build` after changing `src/lib.rs`; the pure-Python
  `PyRouter` is the fallback when it's missing.
- `example/` is an in-repo demo app (in-memory CRUD, no database) — it is not
  shipped as part of the `gunbullet` package.
- `plan.md` and `feature.md` (Russian) are planning scratch; `dist/`, `target/`,
  `.qwen/` are build/tooling artifacts, not framework source.
