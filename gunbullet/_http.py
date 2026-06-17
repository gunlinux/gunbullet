from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs as _parse_qs

import msgspec

if TYPE_CHECKING:
    from gunbullet.app import GunbulletApp


class State:
    """A simple attribute-access namespace backed by a dict, FastAPI-style.

    Used for ``app.state`` to stash arbitrary objects (db pools, clients, ...)
    that should live for the whole application and be reachable from handlers
    via ``request.app.state``.
    """

    __slots__ = ("_state",)

    def __init__(self, state: dict[str, Any] | None = None):
        object.__setattr__(self, "_state", state if state is not None else {})

    def __getattr__(self, name: str) -> Any:
        try:
            return self._state[name]
        except KeyError:
            raise AttributeError(f"state has no attribute {name!r}") from None

    def __setattr__(self, name: str, value: Any) -> None:
        self._state[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self._state[name]
        except KeyError:
            raise AttributeError(f"state has no attribute {name!r}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._state

    def __repr__(self) -> str:
        return f"State({self._state!r})"


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
        "app",
        "state",
        "_raw_headers",
        "_query_string",
        "_headers",
        "_query",
        "_cookies",
    )

    def __init__(
        self,
        scope: dict[str, Any],
        body: bytes = b"",
        *,
        app: "GunbulletApp",
    ):
        self.method: str = scope.get("method", "").upper()
        self.path: str = scope.get("path", "")
        self.body: bytes = body
        self.app: "GunbulletApp" = app
        s = scope.get("state")
        self.state: dict[str, Any] = s if s is not None else {}
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
