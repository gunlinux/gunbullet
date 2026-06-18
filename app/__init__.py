import os

from msgspec import Struct

from gunbullet import GunbulletApp, Request, Response

from app.db import init_db, open_db

base_d = {"name": "loki", "age": 37}

DB_URI = os.environ.get("APP_DB_URI", "users.db")


class UserResponse(Struct):
    name: str
    age: int


class AgeResponse(Struct):
    age: int


class User(Struct):
    id: int
    name: str
    email: str
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

    @app.lifespan
    async def lifespan(app: GunbulletApp):
        conn = open_db(DB_URI)
        init_db(conn)
        # Yielded mapping is surfaced as ``request.state`` under both ASGI and
        # RSGI, so handlers reach the connection via ``request.state["db"]``.
        yield {"db": conn}
        conn.close()

    @app.route("/")
    async def index_page(_: Request) -> Response[UserResponse]:
        return 200, UserResponse(**base_d)

    @app.route("/age/<age>")
    async def param_page(
        request: Request,
        age: int,
    ) -> Response[AgeResponse]:
        return 200, AgeResponse(age=age)

    @app.route("/users")
    async def users_list(request: Request) -> Response[list[User]]:
        # Synchronous sqlite3 queried inline -- the table is tiny and cached, so
        # the query is ~2 us; no thread offload or pool. See app/db.py.
        conn = request.state["db"]
        rows = conn.execute(
            "SELECT id, name, email, age FROM users ORDER BY id"
        ).fetchall()
        return 200, [User(**dict(row)) for row in rows]

    @app.route("/users/<user_id>")
    async def user_detail(request: Request, user_id: int) -> Response[User]:
        conn = request.state["db"]
        row = conn.execute(
            "SELECT id, name, email, age FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return 404, {"error": "not_found", "detail": f"user {user_id}"}
        return 200, User(**dict(row))

    app.add_exception_handler(ValueError, _domain_error_handler)

    return app
