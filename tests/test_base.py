from msgspec import Struct

from bullet import BulletApp, Request
from bullet.testclient import TestClient


class UserResponse(Struct):
    name: str
    age: int


def test_index_route(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.json() == {"name": "loki", "age": 37}


def test_path_param_converted_to_int(client: TestClient) -> None:
    response = client.get("/age/37")
    assert response.status_code == 200
    assert response.json() == {"age": 37}


def test_path_param_bad_type_returns_400(client: TestClient) -> None:
    response = client.get("/age/notanumber")
    assert response.status_code == 400
    assert response.json() == {"error": "invalid integer: 'notanumber'"}


def test_unknown_route_returns_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_handler_returning_str_is_json_encoded(app: BulletApp) -> None:
    """Handler returning a plain str is sent as a JSON string."""

    async def str_handler(request: Request) -> str:
        return "hello world"

    app.add_handler("/str", str_handler)

    with TestClient(app) as client:
        response = client.get("/str")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert response.json() == "hello world"


def test_handler_returning_dict_is_json_encoded(app: BulletApp) -> None:
    """Handler returning a dict is JSON-serialized."""

    async def dict_handler(request: Request) -> dict:
        return {"status": "ok", "count": 42}

    app.add_handler("/dict", dict_handler)

    with TestClient(app) as client:
        response = client.get("/dict")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert response.json() == {"status": "ok", "count": 42}


def test_handler_returning_msgspec_struct_is_json_encoded(app: BulletApp) -> None:
    """Handler returning an msgspec Struct is serialized via msgspec.json.encode."""

    async def struct_handler(request: Request) -> UserResponse:
        return UserResponse(name="loki", age=37)

    app.add_handler("/struct", struct_handler)

    with TestClient(app) as client:
        response = client.get("/struct")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert response.json() == {"name": "loki", "age": 37}
