# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`lmao-server` is a learning project: a from-scratch async web micro-framework called **bullet**, built directly on the raw ASGI protocol (`__call__(scope, receive, send)`). No Flask/Django/FastAPI — the point is implementing routing, request parsing, param extraction, validation, and a test client by hand. `msgspec` is the only serialization/validation dependency that the framework itself uses.

Python 3.13+, managed with [`uv`](https://docs.astral.sh/uv/) (`uv.lock` is checked in).

## Commands

```bash
uv sync --dev                       # install deps (incl. linters, pytest)
make dev                            # uv sync --dev + run uvicorn main:app_asgi
uv run uvicorn main:app_asgi        # run the dev server (from repo root)

make check                          # lint + fix + types + test  (run before finishing)
make lint                           # ruff check
make fix                            # ruff check --fix && ruff format
make types                          # pyright
make test                           # pytest

uv run pytest tests/test_params.py::test_query_decoded_with_coercion   # single test
```

Always run from the repo root — imports assume that working directory.

## Architecture

```
main.py            entry point: app_asgi = create_app_asgi()  (served by uvicorn)
app/__init__.py    create_app_asgi() — wires up a BulletApp with example routes
bullet/            the framework (see below)
tests/             pytest suite driving the app through bullet.testclient.TestClient
```

### The `bullet` package — request lifecycle

The flow when a request arrives at `BulletApp.__call__`:

1. **`bullet/app.py` — `BulletApp`** is the ASGI callable. It handles the `lifespan` protocol, drains the request body (skipped for `_BODYLESS` methods: GET/HEAD/OPTIONS/DELETE), then routes:
   - **Static routes** (`"<"` not in pattern) live in `self._static: dict` for O(1) lookup.
   - **Dynamic routes** (`/users/<id>`) live in `self._dynamic: list` and are matched in registration order via compiled regex.
   - Unmatched → 404 `{"error": "Not found"}`.
   - All responses go through `_send_json`, which encodes with `msgspec.json.encode` and sets `Content-Type: application/json; charset=utf-8` + `Content-Length`.

2. **`bullet/_routing.py` — `Handler`** wraps one route + handler coroutine. At registration it inspects the handler signature to build extractor lists. `match(path)` returns the regex groupdict or `None`. `execute()` builds kwargs from the request, calls the handler, and returns `(status, body)`. Any `msgspec.DecodeError` (which `ValidationError` subclasses) during extraction is caught and returned as **400** `{"error": ...}`.

3. **`bullet/params.py` — parameter markers.** Handlers declare where each arg comes from via `Annotated` markers:
   - `Query[MyStruct]` — query string → `msgspec.Struct` (via `msgspec.convert`, lenient coercion).
   - `Body[MyStruct]` — JSON request body → struct (via `msgspec.json.decode`).
   - `Path[MyStruct]` — path params → struct; **`Path[...]` requires a `msgspec.Struct`**, not a bare type.
   - A bare annotated param whose name matches a `<route_param>` (e.g. `age: int`) is coerced directly without a marker struct.
   - The `request: Request` first arg is always passed and is skipped by all marker logic.

4. **`validate_handler()` (in `_routing.py`)** runs at registration time (`add_handler` / `@app.route`). It raises `ValueError` if any `<route_param>` is not covered by a handler arg or `Path` struct field. This is fail-fast registration validation — most "errors" in tests are `pytest.raises(ValueError)` at registration, not request-time failures.

5. **`bullet/_http.py` — `Request`** parses the ASGI `scope` lazily: `headers` (case-insensitive `Headers`), `query`, and `cookies` are computed on first access and cached. `request.json(type=...)` decodes the body via msgspec. `request.state` exposes the ASGI scope `state` dict populated by the lifespan (see below).

### Lifespan

`BulletApp` supports a FastAPI-style lifespan via the `@app.lifespan` decorator (or the `BulletApp(lifespan=...)` constructor kwarg). The registered function runs startup code, `yield`s once, then runs shutdown code; an optional dict yielded at the `yield` is merged into the ASGI scope `state` and surfaces on `request.state`:

```python
@app.lifespan
async def lifespan(app):
    pool = await connect()      # startup
    yield {"db": pool}          # state -> request.state["db"]
    await pool.close()          # shutdown
```

A plain async generator is auto-wrapped with `contextlib.asynccontextmanager`; an already-wrapped CM factory is accepted as-is. `_as_lifespan` (in `app.py`) normalizes both forms. The protocol itself is driven by `BulletApp._run_lifespan`, which enters the CM on `lifespan.startup` (sending `...startup.failed` with the exception message on error) and exits it on `lifespan.shutdown`. With no lifespan registered it just acks the events.

### Handler contract

Handlers are `async def`, take `request: Request` first, and return `str | dict | msgspec.Struct`. There is currently **no response abstraction**: success status is always 200 (400/404 are produced by the framework, not the handler). No middleware, streaming/SSE, route groups, or custom status codes from handlers yet — see `feature.md` / `plan.md` for the roadmap.

### `bullet/testclient.py` — TestClient

A **synchronous** test client modeled on Starlette's, built on `httpx2` + `anyio`. It does not hit the network: `_ASGITransport` builds a `scope`, drives the app on a worker event loop via an anyio blocking portal, and reassembles `http.response.*` messages into an `httpx.Response`. Using it as a context manager (`with TestClient(app) as client:`) additionally runs the app's `lifespan` startup/shutdown on a persistent portal. This is the standard way tests exercise the app.

## Notes

- `AGENTS.md` (`# QWEN.md`) is an older description and is partly stale (it predates the split of `bullet/__init__.py` into modules and references an `app/asgi.py` that no longer exists). Prefer the actual source.
- Root-level scratch files are **not** part of the framework: `fapi.py` (FastAPI app for benchmark comparison), `bench.sh` + `fapi.md` (wrk benchmark results vs FastAPI), `excp.py` (exception-handling experiment), `debug.py` (alternative uvicorn runner). `dist/`, `.qwen/`, and the planning docs (`plan.md`, `feature.md` — in Russian) are likewise non-framework.
