from typing import Awaitable, Callable, TypeVar

import msgspec


HandlerFunc = TypeVar(
    "HandlerFunc", bound=Callable[..., Awaitable[str | dict | msgspec.Struct]]
)


class BadRequest(Exception):
    """Raised when a URL parameter fails type conversion."""
