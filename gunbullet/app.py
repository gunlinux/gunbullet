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
from gunbullet._router import Router
from gunbullet._routing import Handler, validate_handler
from gunbullet._types import HandlerFunc

if TYPE_CHECKING:
    from gunbullet._types import HandlerReturn

_BODYLESS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})
_CT_JSON = (b"content-type", b"application/json; charset=utf-8")
_CT_JSON_RSGI = ("content-type", "application/json; charset=utf-8")

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
        self._router = Router()
        self._handlers: list[Handler] = []
        self.exceptions_handlers: dict[
            type[Exception] | int, Callable[..., Awaitable["HandlerReturn"]]
        ] = {}
        self._lifespan: Optional[Lifespan] = (
            _as_lifespan(lifespan) if lifespan is not None else None
        )
        self._lifespan_cm: Optional[AsyncContextManager[Any]] = None
        # State yielded by the lifespan, surfaced as ``request.state`` under
        # RSGI (which, unlike ASGI, has no per-request scope state to carry it).
        self._lifespan_state: dict[str, Any] = {}

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
        route_id = len(self._handlers)
        self._handlers.append(h)
        self._router.add(route, route_id)

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

        method = scope.get("method", "GET").upper()

        body = b""
        if method not in _BODYLESS:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body = event.get("body", b"")
            if event.get("more_body", False):
                # Multi-chunk body: collect and join once rather than repeatedly
                # reallocating with ``+=`` (which is O(n^2) over the chunks).
                chunks = [body]
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    chunks.append(event.get("body", b""))
                    if not event.get("more_body", False):
                        break
                body = b"".join(chunks)

        request = Request(scope, body, app=self, method=method)
        resolved = await self._route(request, method, scope["path"])
        if resolved is not None:
            await _send_json(send, resolved[0], resolved[1])

    async def __rsgi__(self, scope: Any, protocol: Any) -> None:
        """Granian RSGI entry point (HTTP only).

        Unlike ASGI, Granian's Rust core reads the socket and assembles the
        whole body itself: ``await protocol()`` returns the complete request
        body in a single await (no per-chunk ``receive()`` loop), and the
        response goes out in one ``response_bytes`` call instead of the two-event
        ASGI send. WebSocket scopes are not supported and are ignored.
        """
        if scope.proto != "http":
            return

        method = scope.method.upper()

        body = b""
        if method not in _BODYLESS:
            try:
                body = await protocol()
            except RuntimeError:
                # RSGIProtocolClosed / RSGIProtocolError both subclass
                # RuntimeError -- the client went away mid-body.
                return

        request = Request.from_rsgi(scope, body, app=self, state=self._lifespan_state)
        resolved = await self._route(request, method, scope.path)
        if resolved is None:
            # A handler raised with no registered exception handler. Unlike ASGI
            # -- where the server has its own fallback for a never-answered
            # request -- Granian's RSGI core would leave the connection hanging
            # if we never call ``response_bytes``, so emit an explicit 500.
            resolved = (500, {"error": "Internal server error"})
        _send_json_rsgi(protocol, resolved[0], resolved[1])

    async def _route(
        self, request: Request, method: str, path: str
    ) -> tuple[int, Any] | None:
        """Match the path, run the handler, and resolve a ``(status, body)``.

        Shared by the ASGI (``__call__``) and RSGI (``__rsgi__``) entry points;
        only body reading and response sending differ between them. Returns
        ``None`` when a matched handler raised with no registered exception
        handler. The ASGI caller then sends nothing (leaving the server's own
        fallback to answer), while the RSGI caller emits an explicit 500 since
        Granian has no such fallback.
        """
        candidates = self._router.match(path)
        for params, route_id in candidates:
            handler = self._handlers[route_id]
            if handler.allows(method):
                return await self._resolve(request, handler, params or None)
        if candidates:
            return 405, {"error": "Method not allowed"}
        return 404, {"error": "Not found"}

    async def _resolve(
        self,
        request: Request,
        handler: Handler,
        params: dict[str, str] | None,
    ) -> tuple[int, Any] | None:
        try:
            result = await handler.execute(request, params)
        except Exception as exc:
            exc_handler = self.exceptions_handlers.get(type(exc), None)
            if exc_handler is None:
                return None
            result = await exc_handler(request, exc)
        return _normalize_response(result)

    # --- RSGI lifespan bridge -------------------------------------------------
    # RSGI has no ASGI-style lifespan protocol; Granian instead calls these sync
    # hooks with the event loop before/after serving (loop is not yet running),
    # so we drive the async lifespan context manager with ``run_until_complete``.

    def __rsgi_init__(self, loop: Any) -> None:
        if self._lifespan is None:
            return
        cm = self._lifespan(self)
        result = loop.run_until_complete(cm.__aenter__())
        # Retain the context manager only after a successful startup, so a
        # failed ``__aenter__`` (which Granian lets propagate, aborting the
        # worker) never leaves ``__rsgi_del__`` exiting a context that never
        # entered. The yielded mapping becomes ``request.state``, mirroring the
        # ASGI lifespan's scope-state injection.
        self._lifespan_cm = cm
        if result is not None:
            self._lifespan_state.update(result)

    def __rsgi_del__(self, loop: Any) -> None:
        if self._lifespan_cm is not None:
            loop.run_until_complete(self._lifespan_cm.__aexit__(None, None, None))


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


def _send_json_rsgi(protocol, status: int, body: str | dict | msgspec.Struct) -> None:
    """Send a JSON response over the RSGI protocol.

    A single ``response_bytes`` call (no start/body split). RSGI headers are
    ``(str, str)`` pairs, not the ``bytes`` tuples ASGI uses.
    """
    raw = msgspec.json.encode(body)
    headers = [
        _CT_JSON_RSGI,
        ("content-length", str(len(raw))),
    ]
    protocol.response_bytes(status, headers, raw)
