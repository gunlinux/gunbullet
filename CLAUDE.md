# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A from-scratch learning project implementing raw **WSGI**, **ASGI**, and **RSGI** applications with **no web framework** (no Flask/Django/FastAPI). Routing, request parsing, and HTML/JSON responses are all hand-written against the bare server interfaces. The point is to work directly with each protocol contract, so do not introduce a framework or abstraction layer unless asked.

The repo has **two deliberate "same thing modelled three ways" axes**, so things can be compared side by side:

1. **Server interface** — `app/wsgi.py`, `app/asgi.py`, `app/rsgi.py` implement the *same* HTML app (routes `/`, `/about`, `/contact`, else 404) three times, once per interface.
2. **Serialization library** — `app/schema/` models `app/data/users.json` three times (pydantic / marshmallow / msgspec) behind a common interface.

The ASGI module additionally exposes a JSON **`/api` route family** that ties the two axes together: it validates and re-serializes the users dataset with each library. **WSGI and RSGI have no `/api` parity** — the JSON routes currently live only in ASGI.

## Environment & commands

The project uses [`uv`](https://docs.astral.sh/uv/) with `uv.lock` checked in. Python 3.12+ required.

```bash
uv sync                                          # install deps into .venv

# WSGI app (app_wsgi)
uv run gunicorn main:app_wsgi                     # gunicorn
uv run granian --interface wsgi main:app_wsgi     # granian

# ASGI app (app_asgi)
uv run uvicorn main:app_asgi                       # uvicorn
uv run granian --interface asgi main:app_asgi      # granian

# RSGI app (app_rsgi) — Granian's native interface, granian only
uv run granian --interface rsgi main:app_rsgi

# Validate the bundled users.json with all three schema libs
uv run python -m app.schema
```

**Run servers from the repo root.** `app/users.py` opens `app/data/users.json` via a hardcoded *relative* path, and `main.py` instantiates `Users()` at import time, so launching from a different working directory breaks startup. (The `/api` routes themselves read the data via `app.schema.common.DATA_FILE`, an absolute path, and are unaffected.)

There are currently **no tests, linter, or formatter configured** — `pyproject.toml` declares the three server runtimes (granian, gunicorn, uvicorn) plus the three schema libs (marshmallow, msgspec, pydantic). `python -m app.schema` is the closest thing to a smoke test.

## Architecture

- `main.py` — top-level module the servers import. Exposes `app_wsgi`, `app_asgi`, `app_rsgi` via the `create_app_*` factories, and eagerly constructs `Users()`.
- `app/__init__.py` — re-exports `application` from each server module and defines the trivial `create_app_wsgi()` / `create_app_asgi()` / `create_app_rsgi()` factories.
- `app/wsgi.py` — synchronous WSGI. `application(environ, start_response)` reads `environ["PATH_INFO"]`, dispatches to a per-page handler; each handler builds an HTML string, encodes to bytes, sets `Content-Length`, calls `start_response`, returns `[bytes]`.
- `app/asgi.py` — async ASGI. `application(scope, receive, send)` handles the `lifespan` protocol (so servers don't hang), drains the request body events, routes on `scope["path"]`, and emits `http.response.start` + `http.response.body`. Header names/values are **bytes** here. Two send helpers: `send_html` encodes a str body; `send_json` takes **already-encoded bytes** and sets `application/json`.
  - **`/api` route family** (ASGI only): `api_pydantic_page` (also the bare `/api`), `api_marshmallow_page`, `api_msgspec_page`. Each reads `DATA_FILE`, validates it through its library's `UsersResponse`, and re-serializes to JSON bytes — so the three routes return equivalent payloads produced by three different validate→serialize pipelines.
- `app/rsgi.py` — async RSGI (Granian native). `application(scope, protocol)` differs from ASGI: `scope` is an **object** with attribute access (`scope.path`, `scope.method`, `scope.query_string`, `scope.proto`) and `protocol` emits the response. Bails early unless `scope.proto == "http"`. `send_html` calls `protocol.response_bytes(status, headers, body)` — **synchronous** (not awaited), headers are `str` tuples. `home_page` still contains `print(...)`/`dir(...)` debugging scaffolding that can be removed.
- `app/users.py` — `Users` class with a class-level cache of the raw `users.json` *string*, loaded once on first instantiation via a relative path.
- `app/data/users.json` — DummyJSON users payload (~30 users); the data the `/api` routes validate and serve.
- `app/schema/` — the users.json structure modelled three ways. `common.py` holds the shared `DATA_FILE` path and `Role` enum that all three implementations agree on; `pydantic_schema.py` / `marshmallow_schema.py` / `msgspec_schema.py` each define nested models plus a top-level `UsersResponse`. Field names keep the original **camelCase** JSON keys (no aliasing). `python -m app.schema` validates the bundled data with all three.

### Per-interface contract differences to keep straight

| | WSGI | ASGI | RSGI |
|---|---|---|---|
| signature | `(environ, start_response)` | `(scope, receive, send)` | `(scope, protocol)` |
| sync/async | sync | async | async |
| request metadata | `environ` dict (`PATH_INFO`, `REQUEST_METHOD`) | `scope` dict (`scope["path"]`) | `scope` object (`scope.path`) |
| send response | `start_response()` + return `[bytes]` | `await send({...})` events | `protocol.response_bytes(...)` |
| header strings | `str` | `bytes` | `str` |

When adding HTML routes, add a handler and a dispatch branch **in each of the three server modules** for parity — there is no shared route table or registration mechanism. When changing the data model, update **all three** `app/schema/*_schema.py` modules (and `common.py` if a shared type changes) so `python -m app.schema` stays green.
