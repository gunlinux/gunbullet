from msgspec import Struct
from typing import TYPE_CHECKING

from bullet import BulletApp, Request

if TYPE_CHECKING:
    from bullet import Response
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
    assert "error" in response.json()


def test_unknown_route_returns_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


"""
def test_handler_returning_str_is_json_encoded(app: BulletApp) -> None:
    async def str_handler(request: Request) -> "Response[str]":
        return str("hello world")

    app.add_handler("/str", str_handler)

    with TestClient(app) as client:
        response = client.get("/str")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert response.json() == "hello world"
"""


def test_handler_returning_dict_is_json_encoded(app: BulletApp) -> None:
    async def dict_handler(request: Request) -> "Response[dict]":
        return 200, {"status": "ok", "count": 42}

    app.add_handler("/dict", dict_handler)

    with TestClient(app) as client:
        response = client.get("/dict")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert response.json() == {"status": "ok", "count": 42}


def test_handler_returning_msgspec_struct_is_json_encoded(app: BulletApp) -> None:
    async def struct_handler(request: Request) -> "Response[UserResponse]":
        return 200, UserResponse(name="loki", age=37)

    app.add_handler("/struct", struct_handler)

    with TestClient(app) as client:
        response = client.get("/struct")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        assert response.json() == {"name": "loki", "age": 37}
