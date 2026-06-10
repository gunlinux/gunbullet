from bullet import BulletApp, Request
import json

base_d = {"name": "loki", "age": 37}


def create_app_asgi():
    app = BulletApp()

    async def index_page(request: Request) -> bytes:
        print(request)
        print("index_page here")
        body = json.dumps(base_d).encode("utf-8")
        return body

    async def param_page(
        request: Request,
        age: int,
    ) -> bytes:
        temp = {"age": age}
        return json.dumps(temp).encode("utf-8")

    app.add_handler("/", index_page)
    app.add_handler("/age/<age>", param_page)

    return app
