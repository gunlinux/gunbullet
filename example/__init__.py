"""A small, self-contained Gunbullet example app.

This mirrors the shape of FastAPI's tutorial: an in-memory "items" store with
full CRUD, query filtering, typed path params, request-body validation, a
lifespan that seeds the store, and a custom exception handler. It uses no
database so it runs anywhere with just ``gunbullet`` installed.

Run it:

    uv run uvicorn example.main:app_asgi
    # or, on Granian's RSGI core:
    uv run granian --interface rsgi example.main:app_asgi --workers 1 --no-ws

Then:

    curl localhost:8000/
    curl 'localhost:8000/items?limit=2&q=ax'
    curl localhost:8000/items/1
    curl -X POST localhost:8000/items -d '{"name":"Pliers","price":7.5}'
"""

from msgspec import Struct

from gunbullet import (
    Body,
    GunbulletApp,
    HandlerReturn,
    Path,
    Query,
    Request,
    Response,
)


# --- Schemas ----------------------------------------------------------------
# msgspec Structs double as request validation and response serialization: a
# handler that returns ``Response[Item]`` is encoded to JSON, and a ``Body[NewItem]``
# argument is decoded + validated from the request body (a bad body -> 400).


class Item(Struct):
    id: int
    name: str
    price: float
    tags: list[str] = []


class NewItem(Struct):
    """Request body for creating an item (no ``id`` -- the server assigns it)."""

    name: str
    price: float
    tags: list[str] = []


class ItemFilters(Struct):
    """Query-string parameters for listing items, with defaults."""

    limit: int = 20
    q: str = ""


class Greeting(Struct):
    message: str
    docs: str


class ItemPath(Struct):
    item_id: int


# --- Domain errors ----------------------------------------------------------
# A handler raises a plain domain exception; the registered handler turns it into
# an HTTP response, keeping status-code plumbing out of the handlers themselves.


class ItemNotFound(Exception):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} does not exist")
        self.item_id = item_id


async def _handle_not_found(_: Request, exc: Exception) -> Response:
    assert isinstance(exc, ItemNotFound)
    return 404, {"error": "not_found", "detail": str(exc), "item_id": exc.item_id}


def create_app_asgi() -> GunbulletApp:
    app = GunbulletApp()

    # In-memory store. The lifespan seeds it on startup and clears it on
    # shutdown; handlers reach it via ``request.state["items"]``.
    @app.lifespan
    async def lifespan(app: GunbulletApp):
        store: dict[int, Item] = {
            1: Item(id=1, name="Axe", price=12.0, tags=["tools"]),
            2: Item(id=2, name="Hammer", price=9.5, tags=["tools", "metal"]),
            3: Item(id=3, name="Wax", price=3.25, tags=["cleaning"]),
        }
        # ``app.state`` holds long-lived, app-wide data; here a simple counter
        # for assigning new item ids. Reachable via ``request.app.state``.
        app.state.next_id = max(store) + 1
        yield {"items": store}
        store.clear()

    @app.get("/")
    async def index(_: Request) -> HandlerReturn[Greeting]:
        # A bare return value defaults to status 200; the explicit ``(status, body)``
        # tuple form is used elsewhere where the status varies.
        return Greeting(message="gunbullet example", docs="see example/__init__.py")

    @app.get("/items")
    async def list_items(
        request: Request, filters: Query[ItemFilters]
    ) -> Response[list[Item]]:
        # GET /items?q=ax&limit=2  -> case-insensitive name filter, then limited.
        store: dict[int, Item] = request.state["items"]
        items = [i for i in store.values() if filters.q.lower() in i.name.lower()]
        return 200, items[: filters.limit]

    @app.get("/items/<item_id>")
    async def get_item(request: Request, path: Path[ItemPath]) -> Response[Item]:
        # ``Path[ItemPath]`` groups route params into a struct (coerced + validated);
        # GET /items/foo -> 400 because ``item_id`` is not an int.
        store: dict[int, Item] = request.state["items"]
        item = store.get(path.item_id)
        if item is None:
            raise ItemNotFound(path.item_id)
        return 200, item

    @app.post("/items")
    async def create_item(request: Request, body: Body[NewItem]) -> Response[Item]:
        store: dict[int, Item] = request.state["items"]
        new_id: int = request.app.state.next_id
        request.app.state.next_id = new_id + 1
        item = Item(id=new_id, name=body.name, price=body.price, tags=body.tags)
        store[new_id] = item
        return 201, item

    @app.delete("/items/<item_id>")
    async def delete_item(request: Request, item_id: int) -> Response:
        # A bare typed arg whose name matches the ``<route_param>`` is coerced
        # directly -- no struct needed for a single param.
        store: dict[int, Item] = request.state["items"]
        if store.pop(item_id, None) is None:
            raise ItemNotFound(item_id)
        return 204, {}

    app.add_exception_handler(ItemNotFound, _handle_not_found)

    return app
