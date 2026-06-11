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

    async def index_page(request: Request) -> UserResponse:
        return UserResponse(**base_d)

    async def param_page(
        request: Request,
        age: int,
    ) -> AgeResponse:
        return AgeResponse(age=age)

    app.add_handler("/", index_page)
    app.add_handler("/age/<age>", param_page)

    return app
