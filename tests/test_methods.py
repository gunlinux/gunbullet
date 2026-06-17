from gunbullet import GunbulletApp, Path, Request
from gunbullet.testclient import TestClient
from msgspec import Struct


class AgePath(Struct):
    age: int


def test_same_path_dispatches_by_method(app: GunbulletApp) -> None:
    @app.get("/items")
    async def list_items(request: Request) -> dict:
        return {"verb": "get"}

    @app.post("/items")
    async def create_item(request: Request) -> dict:
        return {"verb": "post"}

    with TestClient(app) as client:
        assert client.get("/items").json() == {"verb": "get"}
        assert client.post("/items").json() == {"verb": "post"}


def test_wrong_method_returns_405(app: GunbulletApp) -> None:
    @app.get("/only-get")
    async def only_get(request: Request) -> dict:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.post("/only-get")
        assert response.status_code == 405
        assert response.json() == {"error": "Method not allowed"}


def test_unknown_path_still_returns_404(app: GunbulletApp) -> None:
    @app.get("/known")
    async def known(request: Request) -> dict:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.post("/unknown")
        assert response.status_code == 404
        assert response.json() == {"error": "Not found"}


def test_route_without_methods_defaults_to_all(app: GunbulletApp) -> None:
    @app.route("/any")
    async def any_verb(request: Request) -> dict:
        return {"method": request.method}

    with TestClient(app) as client:
        assert client.get("/any").json() == {"method": "GET"}
        assert client.post("/any").json() == {"method": "POST"}
        assert client.delete("/any").json() == {"method": "DELETE"}


def test_dynamic_route_restricted_by_method(app: GunbulletApp) -> None:
    @app.get("/widgets/<age>")
    async def get_widget(request: Request, path: Path[AgePath]) -> dict:
        return {"wid": path.age}

    with TestClient(app) as client:
        assert client.get("/widgets/42").json() == {"wid": 42}
        assert client.post("/widgets/42").status_code == 405


def test_verb_shortcut_extracts_path_params(app: GunbulletApp) -> None:
    @app.post("/score/<age>")
    async def set_score(request: Request, age: int) -> dict:
        return {"age": age, "doubled": age * 2}

    with TestClient(app) as client:
        assert client.post("/score/21").json() == {"age": 21, "doubled": 42}
