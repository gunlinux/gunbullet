import json
import pytest
from msgspec import Struct
from typing import TYPE_CHECKING

from bullet import BulletApp, Body, Path, Query, Request
from bullet.testclient import TestClient

if TYPE_CHECKING:
    from bullet import Response


# --- shared structs ---


class UserPath(Struct):
    user_id: int


class PostPath(Struct):
    user_id: int
    post_id: int


class SearchQuery(Struct):
    q: str
    limit: int = 10


class CreateUser(Struct):
    name: str
    age: int


# --- Query[T] ---


def test_query_decoded_with_coercion() -> None:
    app = BulletApp()

    async def search(request: Request, query: Query[SearchQuery]) -> "Response[dict]":
        return 200, {"q": query.q, "limit": query.limit}

    app.add_handler("/search", search)

    with TestClient(app) as client:
        response = client.get("/search?q=hello&limit=5")
        assert response.status_code == 200
        assert response.json() == {"q": "hello", "limit": 5}


def test_query_default_applied_when_param_omitted() -> None:
    app = BulletApp()

    async def search(request: Request, query: Query[SearchQuery]) -> "Response[dict]":
        return 200, {"q": query.q, "limit": query.limit}

    app.add_handler("/search", search)

    with TestClient(app) as client:
        response = client.get("/search?q=world")
        assert response.status_code == 200
        assert response.json() == {"q": "world", "limit": 10}


def test_query_400_on_bad_type() -> None:
    app = BulletApp()

    async def search(request: Request, query: Query[SearchQuery]) -> "Response[dict]":
        return 200, {}

    app.add_handler("/search", search)

    with TestClient(app) as client:
        response = client.get("/search?q=hi&limit=notanumber")
        assert response.status_code == 400
        assert "error" in response.json()


def test_query_400_on_missing_required_field() -> None:
    app = BulletApp()

    async def search(request: Request, query: Query[SearchQuery]) -> "Response[dict]":
        return 200, {}

    app.add_handler("/search", search)

    with TestClient(app) as client:
        response = client.get("/search")
        assert response.status_code == 400
        assert "error" in response.json()


# --- Body[T] ---


def test_body_decoded_from_json() -> None:
    app = BulletApp()

    async def create(request: Request, body: Body[CreateUser]) -> "Response[dict]":
        return 200, {"name": body.name, "age": body.age}

    app.add_handler("/users", create)

    with TestClient(app) as client:
        response = client.post(
            "/users", content=json.dumps({"name": "loki", "age": 37})
        )
        assert response.status_code == 200
        assert response.json() == {"name": "loki", "age": 37}


def test_body_400_on_invalid_json() -> None:
    app = BulletApp()

    async def create(request: Request, body: Body[CreateUser]) -> "Response[dict]":
        return 200, {}

    app.add_handler("/users", create)

    with TestClient(app) as client:
        response = client.post("/users", content=b"not json")
        assert response.status_code == 400
        assert "error" in response.json()


def test_body_400_on_missing_field() -> None:
    app = BulletApp()

    async def create(request: Request, body: Body[CreateUser]) -> "Response[dict]":
        return 200, {}

    app.add_handler("/users", create)

    with TestClient(app) as client:
        response = client.post("/users", content=json.dumps({"name": "loki"}))
        assert response.status_code == 400
        assert "error" in response.json()


# --- Path[T] ---


def test_path_single_param() -> None:
    app = BulletApp()

    async def get_user(request: Request, path: Path[UserPath]) -> "Response[dict]":
        return 200, {"user_id": path.user_id}

    app.add_handler("/users/<user_id>", get_user)

    with TestClient(app) as client:
        response = client.get("/users/42")
        assert response.status_code == 200
        assert response.json() == {"user_id": 42}


def test_path_multi_param() -> None:
    app = BulletApp()

    async def get_post(request: Request, path: Path[PostPath]) -> "Response[dict]":
        return 200, {"user_id": path.user_id, "post_id": path.post_id}

    app.add_handler("/users/<user_id>/posts/<post_id>", get_post)

    with TestClient(app) as client:
        response = client.get("/users/1/posts/99")
        assert response.status_code == 200
        assert response.json() == {"user_id": 1, "post_id": 99}


def test_path_400_on_bad_type() -> None:
    app = BulletApp()

    async def get_user(request: Request, path: Path[UserPath]) -> "Response[dict]":
        return 200, {}

    app.add_handler("/users/<user_id>", get_user)

    with TestClient(app) as client:
        response = client.get("/users/notanumber")
        assert response.status_code == 400
        assert "error" in response.json()


# --- Combined Path + Query ---


def test_combined_path_and_query() -> None:
    app = BulletApp()

    async def list_posts(
        request: Request,
        path: Path[UserPath],
        query: Query[SearchQuery],
    ) -> "Response[dict]":
        return 200, {"user_id": path.user_id, "q": query.q, "limit": query.limit}

    app.add_handler("/users/<user_id>/posts", list_posts)

    with TestClient(app) as client:
        response = client.get("/users/7/posts?q=test&limit=3")
        assert response.status_code == 200
        assert response.json() == {"user_id": 7, "q": "test", "limit": 3}


# --- Registration errors ---


def test_path_non_struct_raises() -> None:
    app = BulletApp()

    async def bad(request: Request, path: Path[int]) -> "Response[dict]":
        return 200, {}

    with pytest.raises(ValueError, match="msgspec.Struct"):
        app.add_handler("/x/<x>", bad)


def test_route_param_not_covered_raises() -> None:
    app = BulletApp()

    async def bad(request: Request) -> "Response[dict]":
        return 200, {}

    with pytest.raises(ValueError, match="not covered"):
        app.add_handler("/items/<id>", bad)


def test_bare_route_param_coerced() -> None:
    app = BulletApp()

    async def get_user(request: Request, user_id: int) -> "Response[dict]":
        return 200, {"user_id": user_id}

    app.add_handler("/users/<user_id>", get_user)

    with TestClient(app) as client:
        response = client.get("/users/42")
        assert response.status_code == 200
        assert response.json() == {"user_id": 42}
