from typing import Awaitable, Callable, Any
import dataclasses
import inspect
import json
from urllib.parse import parse_qs as _parse_qs

import re

param_reg = re.compile(r"<([\w]+)>")


def _json_dumps(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


def validate_handler(path: str, handler: Callable[..., Awaitable[bytes]]) -> None:
    """Verify every ``<param>`` in *path* has a matching handler annotation without a default."""
    params = set(param_reg.findall(path))
    sig = inspect.signature(handler)
    for name, p in sig.parameters.items():
        if name == "request":
            continue
        if name not in params:
            continue
        if p.default is not inspect.Parameter.empty:
            raise ValueError(f"route param '{name}' must not have a default value")
        params.discard(name)
    if params:
        raise ValueError(
            f"handler missing annotations for route params: {', '.join(sorted(params))}"
        )


def _compile_route(pattern: str) -> re.Pattern:
    """Convert a Flask-style route pattern like ``/age/<age>`` into a compiled regex."""
    parts = re.split(r"(<\w+>)", pattern)
    escaped = ""
    for part in parts:
        m = re.fullmatch(r"<(\w+)>", part)
        if m:
            escaped += f"(?P<{m[1]}>[^/]+)"
        else:
            escaped += re.escape(part)
    return re.compile(f"^{escaped}$")


class BadRequest(Exception):
    """Raised when request parameters fail validation (bad types, bad values)."""


def _convert_param(value: str, annotation: type) -> Any:
    """Convert a string param to the type specified in the handler annotation."""
    if annotation is int:
        try:
            return int(value)
        except ValueError:
            raise BadRequest(f"invalid integer: {value!r}")
    if annotation is float:
        try:
            return float(value)
        except ValueError:
            raise BadRequest(f"invalid float: {value!r}")
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

    async def execute(
        self, request: Request, params: dict[str, str]
    ) -> tuple[int, bytes]:
        kwargs: dict[str, Any] = {}
        try:
            for name, value in params.items():
                annotation = self.annotations.get(name, str)
                kwargs[name] = _convert_param(value, annotation)
        except BadRequest as exc:
            return 400, _json_dumps({"error": str(exc)})
        return 200, await self.handler(request, **kwargs)


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

        body = b""
        more_body = scope.get("method", "GET").upper() not in {
            "GET",
            "HEAD",
            "OPTIONS",
            "DELETE",
        }
        while more_body:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            more_body = event.get("more_body", False)
            body += event.get("body", b"")

        path = scope["path"]
        request = Request(scope, body)

        for handler in self.handlers:
            params = handler.match(path)
            if params is not None:
                status, response_body = await handler.execute(request, params)
                await self.send_json(send, status, response_body)
                return

        await self.send_json(send, 404, _json_dumps({"error": "Not found"}))

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
