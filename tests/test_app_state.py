import pytest

from gunbullet import GunbulletApp, Request, State
from gunbullet.testclient import TestClient


def test_state_attribute_access() -> None:
    state = State()
    state.db = "pool"
    assert state.db == "pool"
    assert "db" in state
    assert "missing" not in state


def test_state_missing_attribute_raises() -> None:
    state = State()
    with pytest.raises(AttributeError):
        _ = state.nope


def test_state_delete_attribute() -> None:
    state = State({"db": "pool"})
    del state.db
    assert "db" not in state
    with pytest.raises(AttributeError):
        del state.db


def test_app_has_state_by_default() -> None:
    app = GunbulletApp()
    assert isinstance(app.state, State)


def test_app_state_reaches_handler_via_request() -> None:
    app = GunbulletApp()
    app.state.greeting = "hello"

    async def index(request: Request) -> dict:
        return {"greeting": request.app.state.greeting}

    app.add_handler("/", index)

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"greeting": "hello"}


def test_lifespan_can_populate_app_state() -> None:
    app = GunbulletApp()

    @app.lifespan
    async def lifespan(app: GunbulletApp):
        app.state.db = "connected"  # set on global state at startup
        yield
        app.state.db = "closed"  # shutdown

    async def index(request: Request) -> dict:
        return {"db": request.app.state.db}

    app.add_handler("/", index)

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"db": "connected"}

    assert app.state.db == "closed"


def test_app_state_is_global_across_requests() -> None:
    app = GunbulletApp()
    app.state.counter = 0

    async def bump(request: Request) -> dict:
        request.app.state.counter += 1
        return {"counter": request.app.state.counter}

    app.add_handler("/bump", bump)

    with TestClient(app) as client:
        assert client.get("/bump").json() == {"counter": 1}
        assert client.get("/bump").json() == {"counter": 2}

    assert app.state.counter == 2


def test_request_app_is_the_app_instance() -> None:
    app = GunbulletApp()

    async def index(request: Request) -> dict:
        return {"same": request.app is app}

    app.add_handler("/", index)

    with TestClient(app) as client:
        assert client.get("/").json() == {"same": True}
