# QWEN.md

## Project overview

**lmao-server** — a from-scratch Python ASGI micro-framework called **bullet**, built directly against the raw ASGI protocol contract. No Flask, Django, FastAPI, or any third-party web framework. The point is learning how ASGI works at the wire level.

The project is in active early development. The old learning code (raw WSGI/ASGI/RSGI implementations + schema comparison across pydantic/marshmallow/msgspec) has been removed; only `app/asgi.py` remains as a reference raw ASGI implementation.

## Environment

- Python **3.12+** (see `.python-version`)
- Package manager: [`uv`](https://docs.astral.sh/uv/) with `uv.lock` checked in
- Virtual env: `.venv/`

```bash
uv sync                    # install deps into .venv
uv sync --dev              # install with dev deps (linters, pytest, etc.)
```

## Key commands (from `Makefile`)

| Command | What it does |
|---------|-------------|
| `uv run uvicorn main:app_asgi` | Run the bullet app via uvicorn |
| `make dev` | `uv sync --dev && uv run uvicorn main:app_asgi` |
| `make check` | `make lint && make fix && make types && make test` |
| `make lint` | `uv run ruff check` |
| `make fix` | `uv run ruff check --fix && uv run ruff format` |
| `make types` | `uv run pyright` |
| `make test` | `uv run pytest` |

**Always run servers from the repo root.** Path-dependent imports assume the working directory is `/Users/loki/work/lmao_server`.

## Architecture

```
main.py              ← entry point: `from app import create_app_asgi`
app/
  __init__.py        ← `create_app_asgi()` — builds a BulletApp, registers routes
  asgi.py            ← standalone raw ASGI `application(scope, receive, send)` for reference
bullet/
  __init__.py        ← the bullet micro-framework: BulletApp, Handler, Request
debug.py             ← alternative uvicorn runner (async main)
temp.py              ← throwaway test client (requests)
```

### `main.py`
Imports `create_app_asgi` from `app` and assigns `app_asgi`. Served via `uvicorn main:app_asgi`.

### `app/__init__.py` — the bullet app
Creates a `BulletApp` instance with two routes:
- `GET /` → returns `{"name": "loki", "age": 37}` as JSON
- `GET /age/<age>` → returns `{"age": <age>}` as JSON (using parameter extraction from route pattern)

### `bullet/__init__.py` — the bullet framework

Core classes:

- **`BulletApp`** — callable ASGI application. Handles the `lifespan` protocol, drains request body, iterates `self.handlers` (a `list[Handler]`) for route matching, dispatches to `Handler.execute()`, and sends JSON responses via `send_json`. Falls back to a hardcoded default response for unmatched routes.

- **`Handler`** — wraps a route pattern and async handler callable. `match(path)` uses a compiled regex to extract path parameters as `dict[str, str]` or `None`. `execute(request, params)` converts param values using handler type annotations (`_convert_param`) and calls the handler.

- **`Request`** — parsed ASGI `scope` into typed attributes (method, path, query_string, headers, body, etc.).

- **`Addr`** — dataclass for server/client address (host, port).

Utility functions:

- **`validate_handler(path, handler)`** — verifies that `<param>` placeholders in the route pattern correspond to annotated parameters on the handler (and are not defaulted). Raises `ValueError` if mismatched.

- **`_compile_route(pattern)`** — converts a Flask-style route pattern (`/age/<age>`) into a compiled regex with named capture groups.

- **`_convert_param(value, annotation)`** — converts a string param value to `int`, `float`, or `str` based on the handler's type annotation.

**Known issues / WIP in bullet:**
- Unmatched routes return HTTP 200 with a hardcoded JSON body instead of 404.
- The `Handler` constructor validates params eagerly in `validate_handler`, but doesn't check that the handler has a `request` parameter (the first positional arg).

### `app/asgi.py` — raw ASGI reference
A standalone raw ASGI `application(scope, receive, send)` with:
- Lifespan protocol handling
- Simple path-based routing: `/`, `/about`, `/contact`, `/api/*`
- `send_html` and `send_json` response helpers
- Partial `/api` routes for pydantic, marshmallow, msgspec (some commented out)
- The `home_page` handler is incomplete

This module is **not** wired into `main.py` — it exists as a learning reference. `bullet/__init__.py` has its own independent `BulletApp.send_json` implementation.

## Dependencies (`pyproject.toml`)

### Runtime
- `granian` — RSGI/ASGI/WSGI server
- `gunicorn` — WSGI server
- `uvicorn[standard]` — ASGI server (primary, used for development)
- `msgspec`, `pydantic`, `ujson` — serialization (legacy from the old schema comparison project, may not all be in use currently)

### Dev
- `pyright` — static type checking
- `pytest` — test runner
- `requests` — HTTP client (used in `temp.py`)
- `ruff` — linter + formatter

## Conventions

- No web framework — everything is built directly on the ASGI spec.
- Type annotations are expected for handler parameters (used by `validate_handler`).
- UTF-8 encoding for all string→bytes conversions.
- JSON responses use `application/json; charset=utf-8`.
- Route patterns use Flask-style `<param>` syntax.
- The project has **no tests yet** despite pytest being configured.
