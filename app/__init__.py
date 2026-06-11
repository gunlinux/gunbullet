from bullet import BulletApp, Request

base_d = {"name": "loki", "age": 37}


def create_app_asgi():
    app = BulletApp()

    async def index_page(request: Request) -> dict:
        return base_d

    async def param_page(
        request: Request,
        age: int,
    ) -> dict:
        return {"age": age}

    app.add_handler("/", index_page)
    app.add_handler("/age/<age>", param_page)

    return app
