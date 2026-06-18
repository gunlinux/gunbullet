# Gunbullet example

A small, self-contained app showing the framework end to end: an in-memory
"items" store with CRUD, query filtering, typed path params, body validation, a
lifespan that seeds the store, and a custom exception handler. No database — it
runs anywhere `gunbullet` is installed.

## Run

```bash
uv run uvicorn example.main:app_asgi                                   # ASGI
uv run granian --interface rsgi example.main:app_asgi --workers 1 --no-ws  # RSGI
```

## Try it

```bash
curl localhost:8000/
curl 'localhost:8000/items?limit=2&q=ax'   # case-insensitive name filter
curl localhost:8000/items/1
curl localhost:8000/items/foo              # 400: item_id is not an int
curl localhost:8000/items/99               # 404: custom exception handler
curl -X POST localhost:8000/items -d '{"name":"Pliers","price":7.5}'   # 201
curl -X DELETE localhost:8000/items/1      # 204
```

## What each route demonstrates

| Route                  | Feature                                              |
| ---------------------- | ---------------------------------------------------- |
| `GET /`                | bare return value → 200, `HandlerReturn[Struct]`     |
| `GET /items`           | `Query[Struct]` parsing with defaults                |
| `GET /items/<item_id>` | `Path[Struct]` params, raising a domain exception    |
| `POST /items`          | `Body[Struct]` validation, explicit `201`            |
| `DELETE /items/<id>`   | bare typed path arg, `204`                           |
| (any)                  | `add_exception_handler` mapping a domain error → 404 |

See [`__init__.py`](__init__.py) for the annotated source.
