from typing import Awaitable, Callable, Any, TypeVar
import inspect
import json

import msgspec
from urllib.parse import parse_qs as _parse_qs

import re

param_reg = re.compile(r"<([\w]+)>")

HandlerFunc = TypeVar(
    "HandlerFunc", bound=Callable[..., Awaitable[str | dict | msgspec.Struct]]
)


def validate_handler(
    path: str, handler: Callable[..., Awaitable[str | dict | msgspec.Struct]]
) -> None:
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


class Headers:
    """Case-insensitive string header mapping."""

    __slots__ = ("_store",)

    def __init__(self, raw: list[tuple[bytes, bytes]]):
        self._store: dict[str, str] = {k.lower().decode(): v.decode() for k, v in raw}

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._store.get(name.lower(), default)

    def __getitem__(self, name: str) -> str:
        return self._store[name.lower()]

    def __contains__(self, name: str) -> bool:
        return name.lower() in self._store

    def items(self):
        return self._store.items()

    def __repr__(self) -> str:
        return repr(self._store)


class Request:
    __slots__ = (
        "method",
        "path",
        "body",
        "_raw_headers",
        "_query_string",
        "_headers",
        "_query",
        "_cookies",
    )

    def __init__(self, scope: dict[str, Any], body: bytes = b""):
        self.method: str = scope.get("method", "").upper()
        self.path: str = scope.get("path", "")
        self.body: bytes = body
        self._raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        self._query_string: bytes = scope.get("query_string", b"")
        self._headers: Headers | None = None
        self._query: dict[str, str] | None = None
        self._cookies: dict[str, str] | None = None

    @property
    def headers(self) -> Headers:
        if self._headers is None:
            self._headers = Headers(self._raw_headers)
        return self._headers

    @property
    def query(self) -> dict[str, str]:
        if self._query is None:
            self._query = {
                k: v[0] for k, v in _parse_qs(self._query_string.decode()).items()
            }
        return self._query

    @property
    def cookies(self) -> dict[str, str]:
        if self._cookies is None:
            hdr = self.headers.get("cookie", "")
            c: dict[str, str] = {}
            if hdr:
                for part in hdr.split(";"):
                    k, _, v = part.strip().partition("=")
                    if k:
                        c[k.strip()] = v.strip()
            self._cookies = c
        return self._cookies

    def json(self, type: type = dict) -> Any:
        return msgspec.json.decode(self.body, type=type)


class Handler:
    def __init__(
        self, route: str, handler: Callable[..., Awaitable[str | dict | msgspec.Struct]]
    ):
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
        self,
        request: Request,
        params: dict[str, str] | None = None,
    ) -> tuple[int, str | dict | msgspec.Struct]:
        if not params:
            return 200, await self.handler(request)
        kwargs: dict[str, Any] = {}
        try:
            for name, value in params.items():
                annotation = self.annotations.get(name, str)
                kwargs[name] = _convert_param(value, annotation)
        except BadRequest as exc:
            return 400, {"error": str(exc)}
        return 200, await self.handler(request, **kwargs)


class BulletApp:
    def __init__(self):
        self.handlers: list[Handler] = []

    def add_handler(
        self, route: str, handler: Callable[..., Awaitable[str | dict | msgspec.Struct]]
    ) -> None:
        validate_handler(route, handler=handler)
        self.handlers.append(Handler(route=route, handler=handler))

    def route(self, path: str) -> Callable[[HandlerFunc], HandlerFunc]:
        """Decorator that registers a handler for *path*.

        Usage::

            @app.route("/")
            async def index(request: Request) -> dict:
                return {"hello": "world"}
        """

        def decorator(handler: HandlerFunc) -> HandlerFunc:
            validate_handler(path, handler=handler)
            self.handlers.append(Handler(route=path, handler=handler))
            return handler

        return decorator

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
            if "<" not in path and ">" not in path and handler.path == path:
                status, response_body = await handler.execute(request)
                await self.send_json(send, status, response_body)
                return
            params = handler.match(path)
            if params is not None:
                status, response_body = await handler.execute(request, params)
                await self.send_json(send, status, response_body)
                return

        await self.send_json(send, 404, {"error": "Not found"})

    async def send_json(self, send, status, body):
        """Emit a JSON response. ``body`` is a ``str``, ``dict``, or ``msgspec.Struct``."""
        if isinstance(body, msgspec.Struct):
            raw = msgspec.json.encode(body)
        elif isinstance(body, dict):
            raw = json.dumps(body).encode("utf-8")
        else:
            raw = json.dumps(body).encode("utf-8")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(raw)).encode("utf-8")),
        ]
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": raw})
