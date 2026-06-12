from typing import Awaitable, Callable

import msgspec

from bullet._http import Request
from bullet._routing import Handler, validate_handler
from bullet._types import HandlerFunc

_BODYLESS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})
_CT_JSON = (b"content-type", b"application/json; charset=utf-8")


class BulletApp:
    def __init__(self):
        self._static: dict[str, Handler] = {}
        self._dynamic: list[Handler] = []

    def add_handler(
        self, route: str, handler: Callable[..., Awaitable[str | dict | msgspec.Struct]]
    ) -> None:
        validate_handler(route, handler=handler)
        h = Handler(route=route, handler=handler)
        if "<" not in route:
            self._static[route] = h
        else:
            self._dynamic.append(h)

    def route(self, path: str) -> Callable[[HandlerFunc], HandlerFunc]:
        def decorator(handler: HandlerFunc) -> HandlerFunc:
            self.add_handler(path, handler)
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
        if scope.get("method", "GET").upper() not in _BODYLESS:
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                body += event.get("body", b"")
                if not event.get("more_body", False):
                    break

        path = scope["path"]
        request = Request(scope, body)

        handler = self._static.get(path)
        if handler is not None:
            status, response_body = await handler.execute(request)
            await _send_json(send, status, response_body)
            return

        for handler in self._dynamic:
            params = handler.match(path)
            if params is not None:
                status, response_body = await handler.execute(request, params)
                await _send_json(send, status, response_body)
                return

        await _send_json(send, 404, {"error": "Not found"})


async def _send_json(send, status: int, body: str | dict | msgspec.Struct) -> None:
    raw = msgspec.json.encode(body)
    headers = [
        _CT_JSON,
        (b"content-length", str(len(raw)).encode()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": raw})
