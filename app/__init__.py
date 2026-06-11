from msgspec import Struct

from bullet import BulletApp, Request


base_d = {"name": "loki", "age": 37}


class UserResponse(Struct):
    name: str
    age: int


class AgeResponse(Struct):
    age: int


def create_app_asgi():
    app = BulletApp()

    @app.route("/")
    async def index_page(request: Request) -> UserResponse:
        return UserResponse(**base_d)

    @app.route("/age/<age>")
    async def param_page(
        request: Request,
        age: int,
    ) -> AgeResponse:
        return AgeResponse(age=age)

    return app
