import inspect
import re
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    get_args,
    get_origin,
    TYPE_CHECKING,
)

import msgspec

from bullet._http import Request
from bullet.params import _BodyMarker, _PathMarker, _QueryMarker

if TYPE_CHECKING:
    from bullet import Response

_param_re = re.compile(r"<([\w]+)>")


def _parse_marker(annotation: Any) -> tuple[type, type] | None:
    if get_origin(annotation) is not Annotated:
        return None
    args = get_args(annotation)
    inner = args[0]
    for meta in args[1:]:
        if isinstance(meta, (_QueryMarker, _BodyMarker, _PathMarker)):
            return type(meta), inner
    return None


def validate_handler(path: str, handler: Callable[..., Awaitable["Response"]]) -> None:
    params = set(_param_re.findall(path))
    sig = inspect.signature(handler)
    for name, p in sig.parameters.items():
        if name == "request":
            continue
        marker = _parse_marker(p.annotation)
        if marker is None:
            if name in params:
                params.discard(name)
            continue
        source, typ = marker
        if source is _PathMarker:
            if not (isinstance(typ, type) and issubclass(typ, msgspec.Struct)):
                raise ValueError(f"Path[...] requires a msgspec.Struct, got {typ!r}")
            for field in msgspec.structs.fields(typ):
                if field.name in params:
                    params.discard(field.name)
                elif field.required:
                    raise ValueError(
                        f"Path struct field '{field.name}' is not a route param"
                    )
    if params:
        raise ValueError(
            f"route params not covered by any Path[...] struct: "
            f"{', '.join(sorted(params))}"
        )


def _compile_route(pattern: str) -> re.Pattern[str]:
    parts = re.split(r"(<\w+>)", pattern)
    escaped = ""
    for part in parts:
        m = re.fullmatch(r"<(\w+)>", part)
        if m:
            escaped += f"(?P<{m[1]}>[^/]+)"
        else:
            escaped += re.escape(part)
    return re.compile(f"^{escaped}$")


class Handler:
    def __init__(
        self,
        route: str,
        handler: Callable[..., Awaitable["Response"]],
        methods: frozenset[str] | None = None,
    ):
        self.handler = handler
        self.path = route
        self.methods = methods
        self.pattern = _compile_route(route)
        self._extractors: list[tuple[str, type, type]] = []
        self._bare_path_params: list[tuple[str, type]] = []
        route_params = set(_param_re.findall(route))
        for name, p in inspect.signature(handler).parameters.items():
            if name == "request":
                continue
            marker = _parse_marker(p.annotation)
            if marker is not None:
                self._extractors.append((name, *marker))
            elif name in route_params:
                self._bare_path_params.append((name, p.annotation))

    def allows(self, method: str) -> bool:
        return self.methods is None or method in self.methods

    def match(self, path: str) -> dict[str, str] | None:
        m = self.pattern.match(path)
        if m is None:
            return None
        return m.groupdict()

    async def execute(
        self,
        request: Request,
        params: dict[str, str] | None = None,
    ) -> "Response":
        kwargs: dict[str, Any] = {}
        try:
            for name, source, typ in self._extractors:
                if source is _QueryMarker:
                    kwargs[name] = msgspec.convert(
                        request.query, type=typ, strict=False
                    )
                elif source is _BodyMarker:
                    kwargs[name] = msgspec.json.decode(request.body, type=typ)
                else:  # _PathMarker
                    kwargs[name] = msgspec.convert(params or {}, type=typ, strict=False)
            for name, typ in self._bare_path_params:
                raw = (params or {}).get(name)
                kwargs[name] = msgspec.convert(raw, type=typ, strict=False)
        except msgspec.DecodeError as exc:  # ValidationError subclasses DecodeError
            return 400, {"error": str(exc)}
        return await self.handler(request, **kwargs)
