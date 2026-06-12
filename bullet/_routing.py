import inspect
import re
from typing import Any, Awaitable, Callable

import msgspec

from bullet._http import Request
from bullet._types import BadRequest

_param_re = re.compile(r"<([\w]+)>")


def validate_handler(
    path: str, handler: Callable[..., Awaitable[str | dict | msgspec.Struct]]
) -> None:
    params = set(_param_re.findall(path))
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


def _convert_param(value: str, annotation: type) -> Any:
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
    return value


class Handler:
    def __init__(
        self, route: str, handler: Callable[..., Awaitable[str | dict | msgspec.Struct]]
    ):
        self.handler = handler
        self.path = route
        self.pattern = _compile_route(route)
        self.annotations: dict[str, Any] = handler.__annotations__

    def match(self, path: str) -> dict[str, str] | None:
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
