from typing import Awaitable, Callable, TypeVar, Any

import msgspec

type Response[T = str | dict[str, Any] | msgspec.Struct] = tuple[int, T]


HandlerFunc = TypeVar("HandlerFunc", bound=Callable[..., Awaitable[Response[Any]]])
