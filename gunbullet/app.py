import inspect
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncContextManager,
    Optional,
    TypeVar,
    Awaitable,
    Callable,
    TYPE_CHECKING,
    Iterable,
)

import msgspec

from gunbullet._http import Request, State
from gunbullet._routing import Handler, validate_handler
from gunbullet._types import HandlerFunc

if TYPE_CHECKING:
    from gunbullet._types import HandlerReturn

_BODYLESS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})
_CT_JSON = (b"content-type", b"application/json; charset=utf-8")

Lifespan = Callable[["GunbulletApp"], AsyncContextManager[Any]]
_LifespanFunc = TypeVar("_LifespanFunc")


def _as_lifespan(func: Any) -> Lifespan:
    """Normalize a lifespan into an async context-manager factory.

    Accepts a plain async generator function (wrapped with ``asynccontextmanager``,
    so you can write one FastAPI-style without the decorator) or an already-built
    context-manager factory, which is returned unchanged.
    """
    if inspect.isasyncgenfunction(func):
        return asynccontextmanager(func)
    return func


class GunbulletApp:
    def __init__(self, lifespan: Optional[Lifespan] = None):
        self.state = State()
        self._static: dict[str, list[Handler]] = {}
        self._dynamic: list[Handler] = []
        self.exceptions_handlers: dict[
            type[Exception] | int, Callable[..., Awaitable["HandlerReturn"]]
        ] = {}
        self._lifespan: Optional[Lifespan] = (
            _as_lifespan(lifespan) if lifespan is not None else None
        )
        self._lifespan_cm: Optional[AsyncContextManager[Any]] = None

    def add_exception_handler(
        self,
        exc_class_or_status_code: type[Exception] | int,
        handler: Callable[..., Awaitable["HandlerReturn"]],
    ):
        self.exceptions_handlers[exc_class_or_status_code] = handler

    def add_handler(
        self,
        route: str,
        handler: Callable[..., Awaitable["HandlerReturn"]],
        methods: Iterable[str] | None = None,
    ) -> None:
        validate_handler(route, handler=handler)
        norm = None if methods is None else frozenset(m.upper() for m in methods)
        h = Handler(route=route, handler=handler, methods=norm)
        if "<" not in route:
            self._static.setdefault(route, []).append(h)
        else:
            self._dynamic.append(h)

    def route(
        self, path: str, methods: Iterable[str] | None = None
    ) -> Callable[[HandlerFunc], HandlerFunc]:
        def decorator(handler: HandlerFunc) -> HandlerFunc:
            self.add_handler(path, handler, methods=methods)
            return handler

        return decorator

    def get(self, path: str) -> Callable[[HandlerFunc], HandlerFunc]:
        return self.route(path, methods=["GET"])

    def post(self, path: str) -> Callable[[HandlerFunc], HandlerFunc]:
        return self.route(path, methods=["POST"])

    def put(self, path: str) -> Callable[[HandlerFunc], HandlerFunc]:
        return self.route(path, methods=["PUT"])

    def patch(self, path: str) -> Callable[[HandlerFunc], HandlerFunc]:
        return self.route(path, methods=["PATCH"])

    def delete(self, path: str) -> Callable[[HandlerFunc], HandlerFunc]:
        return self.route(path, methods=["DELETE"])

    def lifespan(self, func: _LifespanFunc) -> _LifespanFunc:
        """Register a startup/shutdown lifespan, FastAPI-style.

        @app.lifespan
        async def lifespan(app):
            db = await connect()   # startup
            yield {"db": db}       # optional state -> request.state
            await db.close()       # shutdown
        """
        self._lifespan = _as_lifespan(func)
        return func

    async def _run_lifespan(self, scope, receive, send):
        state = scope.get("state")
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                try:
                    if self._lifespan is not None:
                        self._lifespan_cm = self._lifespan(self)
                        result = await self._lifespan_cm.__aenter__()
                        if result is not None and state is not None:
                            state.update(result)
                except BaseException as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                try:
                    if self._lifespan_cm is not None:
                        await self._lifespan_cm.__aexit__(None, None, None)
                except BaseException as exc:
                    await send(
                        {"type": "lifespan.shutdown.failed", "message": str(exc)}
                    )
                    return
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._run_lifespan(scope, receive, send)
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

        method = scope.get("method", "GET").upper()
        path = scope["path"]
        request = Request(scope, body, app=self)
        path_matched = False

        for handler in self._static.get(path, ()):
            path_matched = True
            if handler.allows(method):
                await self._dispatch(send, request, handler, None)
                return

        for handler in self._dynamic:
            params = handler.match(path)
            if params is None:
                continue
            path_matched = True
            if handler.allows(method):
                await self._dispatch(send, request, handler, params)
                return

        if path_matched:
            await _send_json(send, 405, {"error": "Method not allowed"})
        else:
            await _send_json(send, 404, {"error": "Not found"})

    async def _dispatch(
        self,
        send,
        request: Request,
        handler: Handler,
        params: dict[str, str] | None,
    ) -> None:
        try:
            result = await handler.execute(request, params)
        except Exception as exc:
            exc_handler = self.exceptions_handlers.get(type(exc), None)
            if exc_handler is not None:
                result = await exc_handler(request, exc)
            else:
                return
        status, response_body = _normalize_response(result)
        await _send_json(send, status, response_body)


def _normalize_response(result: Any) -> tuple[int, Any]:
    """Normalize a handler return into a ``(status, body)`` pair.

    Handlers may return an explicit ``(status, body)`` tuple or a bare body
    (``dict``, ``str``, ``msgspec.Struct``, ...) which defaults to status 200.
    """
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
        return result
    return 200, result


async def _send_json(send, status: int, body: str | dict | msgspec.Struct) -> None:
    raw = msgspec.json.encode(body)
    headers = [
        _CT_JSON,
        (b"content-length", str(len(raw)).encode()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": raw})
