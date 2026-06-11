import io
import math
from typing import Any, Callable, Generator, MutableMapping, Self, TypedDict
from urllib.parse import unquote

import contextlib
import anyio
import anyio.from_thread
import httpx2 as httpx
from anyio.abc import BlockingPortal
from anyio.streams.stapled import StapledObjectStream

from bullet import BulletApp


class _AsyncBackend(TypedDict):
    backend: str
    backend_options: dict[str, Any]


class _ASGITransport(httpx.BaseTransport):
    """Sync httpx transport that drives an async ASGI app through a blocking portal.

    httpx2's built-in ASGITransport only supports the *async* client, so for a
    synchronous TestClient we bridge each request into the app ourselves: build a
    `scope`, run the app on a worker event loop via the portal, and collect the
    `http.response.start` / `http.response.body` messages back into an
    `httpx.Response`.
    """

    def __init__(
        self,
        app: BulletApp,
        portal_factory: Callable[[], "contextlib.AbstractContextManager[BlockingPortal]"],
        raise_app_exceptions: bool = True,
        root_path: str = "",
        client: tuple[str, int] = ("testclient", 50000),
        app_state: dict[str, Any] | None = None,
    ) -> None:
        self.app = app
        self.portal_factory = portal_factory
        self.raise_app_exceptions = raise_app_exceptions
        self.root_path = root_path
        self.client = client
        self.app_state = app_state if app_state is not None else {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        raw_path = request.url.raw_path  # bytes, includes query string

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": request.method,
            "path": unquote(request.url.path),
            "raw_path": raw_path.split(b"?", 1)[0],
            "root_path": self.root_path,
            "scheme": request.url.scheme,
            "query_string": request.url.query,
            "headers": [(k.lower(), v) for k, v in request.headers.raw],
            "server": (host, port),
            "client": self.client,
            "state": self.app_state,
        }

        request_complete = False
        response_started = False
        raw_kwargs: dict[str, Any] = {"stream": io.BytesIO()}

        async def receive() -> MutableMapping[str, Any]:
            nonlocal request_complete
            if request_complete:
                await response_complete.wait()
                return {"type": "http.disconnect"}
            request_complete = True
            return {
                "type": "http.request",
                "body": request.read(),
                "more_body": False,
            }

        async def send(message: MutableMapping[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                raw_kwargs["status_code"] = message["status"]
                raw_kwargs["headers"] = [
                    (k.decode(), v.decode()) for k, v in message.get("headers", [])
                ]
                response_started = True
            elif message["type"] == "http.response.body":
                if request.method != "HEAD":
                    raw_kwargs["stream"].write(message.get("body", b""))
                if not message.get("more_body", False):
                    response_complete.set()

        try:
            with self.portal_factory() as portal:
                response_complete = portal.call(anyio.Event)
                portal.call(self.app, scope, receive, send)
        except BaseException:
            if self.raise_app_exceptions:
                raise

        if self.raise_app_exceptions:
            assert response_started, "TestClient did not receive any response."
        elif not response_started:
            raw_kwargs = {"status_code": 500, "headers": [], "stream": io.BytesIO()}

        raw_kwargs["stream"].seek(0)
        stream = httpx.ByteStream(raw_kwargs.pop("stream").read())
        return httpx.Response(**raw_kwargs, stream=stream, request=request)


class TestClient(httpx.Client):
    """Synchronous test client that drives a BulletApp over the ASGI protocol.

    HTTP requests are routed into the app instead of out to the network. Using the
    client as a context manager additionally runs the app's ``lifespan`` startup /
    shutdown on a persistent background portal; outside the context manager a fresh
    portal is spun up per request.
    """

    __test__ = False

    def __init__(
        self,
        app: BulletApp,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        root_path: str = "",
        backend: str = "asyncio",
        cookies: httpx._types.CookieTypes | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        client: tuple[str, int] = ("testclient", 50000),
    ) -> None:
        self.async_backend = _AsyncBackend(backend=backend, backend_options={})
        self.app = app
        self.app_state: dict[str, Any] = {}
        self.portal: BlockingPortal | None = None

        if headers is None:
            headers = {}
        headers.setdefault("user-agent", "testclient")

        transport = _ASGITransport(
            app=app,
            portal_factory=self._portal_factory,
            raise_app_exceptions=raise_server_exceptions,
            root_path=root_path,
            client=client,
            app_state=self.app_state,
        )
        super().__init__(
            base_url=base_url,
            headers=headers,
            transport=transport,
            follow_redirects=follow_redirects,
            cookies=cookies,
        )

    @contextlib.contextmanager
    def _portal_factory(self) -> Generator[BlockingPortal, None, None]:
        if self.portal is not None:
            yield self.portal
        else:
            with anyio.from_thread.start_blocking_portal(
                **self.async_backend
            ) as portal:
                yield portal

    # --- lifespan support -------------------------------------------------

    def __enter__(self) -> Self:
        with contextlib.ExitStack() as stack:
            self.portal = portal = stack.enter_context(
                anyio.from_thread.start_blocking_portal(**self.async_backend)
            )

            @stack.callback
            def reset_portal() -> None:
                self.portal = None

            send: anyio.create_memory_object_stream[MutableMapping[str, Any] | None] = (
                anyio.create_memory_object_stream(math.inf)
            )
            receive: anyio.create_memory_object_stream[MutableMapping[str, Any]] = (
                anyio.create_memory_object_stream(math.inf)
            )
            for channel in (*send, *receive):
                stack.callback(channel.close)
            self.stream_send = StapledObjectStream(*send)
            self.stream_receive = StapledObjectStream(*receive)
            self.task = portal.start_task_soon(self.lifespan)
            portal.call(self.wait_startup)

            @stack.callback
            def wait_shutdown() -> None:
                portal.call(self.wait_shutdown)

            self.exit_stack = stack.pop_all()

        return self

    def __exit__(self, *args: Any) -> None:
        self.exit_stack.close()

    async def lifespan(self) -> None:
        scope = {"type": "lifespan", "state": self.app_state}
        try:
            await self.app(scope, self.stream_receive.receive, self.stream_send.send)
        finally:
            await self.stream_send.send(None)

    async def wait_startup(self) -> None:
        await self.stream_receive.send({"type": "lifespan.startup"})

        async def receive() -> Any:
            message = await self.stream_send.receive()
            if message is None:
                self.task.result()
            return message

        message = await receive()
        assert message["type"] in (
            "lifespan.startup.complete",
            "lifespan.startup.failed",
        )
        if message["type"] == "lifespan.startup.failed":
            await receive()

    async def wait_shutdown(self) -> None:
        async def receive() -> Any:
            message = await self.stream_send.receive()
            if message is None:
                self.task.result()
            return message

        await self.stream_receive.send({"type": "lifespan.shutdown"})
        message = await receive()
        assert message["type"] in (
            "lifespan.shutdown.complete",
            "lifespan.shutdown.failed",
        )
        if message["type"] == "lifespan.shutdown.failed":
            await receive()
