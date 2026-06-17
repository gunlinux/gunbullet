from typing import Awaitable, Callable, TypeVar, Any

import msgspec

type ResponseBody = str | dict[str, Any] | msgspec.Struct
type Response[T = ResponseBody] = tuple[int, T]

# A handler may return an explicit ``(status, body)`` tuple or a bare body
# (defaulting to status 200); see ``_normalize_response`` in ``gunbullet.app``.
type HandlerReturn[T = ResponseBody] = Response[T] | T


HandlerFunc = TypeVar("HandlerFunc", bound=Callable[..., Awaitable[HandlerReturn[Any]]])
