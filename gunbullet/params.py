from typing import Annotated, TypeVar

T = TypeVar("T")


class _QueryMarker: ...


class _BodyMarker: ...


class _PathMarker: ...


_query_marker = _QueryMarker()
_body_marker = _BodyMarker()
_path_marker = _PathMarker()

Query = Annotated[T, _query_marker]
Body = Annotated[T, _body_marker]
Path = Annotated[T, _path_marker]
