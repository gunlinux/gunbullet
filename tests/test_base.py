from bullet.testclient import TestClient


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
