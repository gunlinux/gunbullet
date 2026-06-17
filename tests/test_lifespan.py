from contextlib import asynccontextmanager

from bullet import BulletApp, Request
from bullet.testclient import TestClient


def test_lifespan_decorator_runs_startup_then_shutdown() -> None:
    events: list[str] = []
    app = BulletApp()

    @app.lifespan
    async def lifespan(app: BulletApp):
        events.append("startup")
        yield
        events.append("shutdown")

    async def index(request: Request) -> dict:
        return {"events": list(events)}

    app.add_handler("/", index)

    with TestClient(app) as client:
        assert events == ["startup"]
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"events": ["startup"]}

    assert events == ["startup", "shutdown"]


def test_lifespan_yielded_state_reaches_request() -> None:
    app = BulletApp()

    @app.lifespan
    async def lifespan(app: BulletApp):
        yield {"db": "connected"}

    async def index(request: Request) -> dict:
        return {"db": request.state["db"]}

    app.add_handler("/", index)

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"db": "connected"}


def test_lifespan_via_constructor_fastapi_style() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(app: BulletApp):
        events.append("up")
        yield
        events.append("down")

    app = BulletApp(lifespan=lifespan)

    async def index(request: Request) -> dict:
        return {}

    app.add_handler("/", index)

    with TestClient(app):
        assert events == ["up"]

    assert events == ["up", "down"]


def test_no_lifespan_still_serves_requests() -> None:
    app = BulletApp()

    async def index(request: Request) -> dict:
        return {"ok": True}

    app.add_handler("/", index)

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
