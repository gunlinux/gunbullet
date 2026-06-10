from typing import Awaitable, Callable, Any
import dataclasses
from urllib.parse import parse_qs as _parse_qs

import re

param_reg = re.compile(r"<([\w]+)>")


def validate_handler(path: str, handler: Callable[..., Awaitable[bytes]]) -> None:
    params = param_reg.findall(path)
    for param in params:
        if param not in handler.__annotations__:
            raise ValueError
        if handler.__defaults__ and param in handler.__defaults__:
            raise ValueError


def _compile_route(pattern: str) -> re.Pattern:
    """Convert a Flask-style route pattern like ``/age/<age>`` into a compiled regex."""
    regex = re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern)
    return re.compile(f"^{regex}$")


def _convert_param(value: str, annotation: type) -> Any:
    """Convert a string param to the type specified in the handler annotation."""
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    if annotation is str:
        return value
    return value


@dataclasses.dataclass
class Addr:
    host: str
    port: int


class Request:
    def __init__(self, scope: dict[str, Any], body: bytes = b""):
        self.method: str = scope.get("method", "")
        self.path: str = scope.get("path", "")
        self.raw_path: bytes = scope.get("raw_path", b"")
        self.query_string: bytes = scope.get("query_string", b"")
        self.body: bytes = body
        self.root_path: str = scope.get("root_path", "")
        self.headers: list[tuple[bytes, bytes]] = scope.get("headers", [])

        server = scope.get("server")
        self.server: Addr | None = Addr(*server) if server else None

        client = scope.get("client")
        self.client: Addr | None = Addr(*client) if client else None

    def get_header(self, name: str) -> str | None:
        target = name.lower().encode()
        for key, val in self.headers:
            if key.lower() == target:
                return val.decode()
        return None

    @property
    def query_params(self) -> dict[str, list[str]]:
        return _parse_qs(self.query_string.decode())


class Handler:
    def __init__(self, route: str, handler: Callable[..., Awaitable[bytes]]):
        self.handler = handler
        self.path = route
        self.pattern = _compile_route(route)
        self.annotations = handler.__annotations__

    def match(self, path: str) -> dict[str, str] | None:
        """Return extracted path parameters if ``path`` matches this route, or None."""
        m = self.pattern.match(path)
        if m is None:
            return None
        return m.groupdict()

    async def execute(self, request: Request, params: dict[str, str]) -> bytes:
        kwargs: dict[str, Any] = {}
        for name, value in params.items():
            annotation = self.annotations.get(name, str)
            kwargs[name] = _convert_param(value, annotation)
        return await self.handler(request, **kwargs)


class BulletApp:
    def __init__(self):
        self.handlers: list[Handler] = []

    def add_handler(self, route: str, handler: Callable[..., Awaitable[Any]]) -> None:
        validate_handler(route, handler=handler)
        self.handlers.append(Handler(route=route, handler=handler))

    async def lifespan(self, scope, receive, send):
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.lifespan(scope, receive, send)
            return

        more_body = True
        body = []
        while more_body:
            event = await receive()
            more_body = event.get("more_body", False)
            body.append(event["body"])
        body = b"".join(body)

        path = scope["path"]
        request = Request(scope, body)

        for handler in self.handlers:
            params = handler.match(path)
            if params is not None:
                await self.send_json(send, 200, await handler.execute(request, params))
                return

        await self.send_json(send, 200, b'{"name": "loki", "age": 37}')

    async def send_json(self, send, status, body):
        """Emit a JSON response. ``body`` is already JSON-encoded bytes."""
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("utf-8")),
        ]
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})
