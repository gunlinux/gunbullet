from msgspec import Struct

from gunbullet import GunbulletApp, Request, Response


base_d = {"name": "loki", "age": 37}


class UserResponse(Struct):
    name: str
    age: int


class AgeResponse(Struct):
    age: int


async def _domain_error_handler(_: Request, exc: Exception) -> Response:
    return (
        404,
        {
            "status_code": 500,
            "error": "domain_error",
            "detail": str(exc) or type(exc).__name__,
        },
    )


def create_app_asgi():
    app = GunbulletApp()

    @app.route("/")
    async def index_page(_: Request) -> Response[UserResponse]:
        return 200, UserResponse(**base_d)

    @app.route("/age/<age>")
    async def param_page(
        request: Request,
        age: int,
    ) -> Response[AgeResponse]:
        return 200, AgeResponse(age=age)

    app.add_exception_handler(ValueError, _domain_error_handler)

    return app
