"""Pure-Python routing table.

This is the fallback backend used when the compiled Rust router
(``gunbullet._gunbullet_router``) is not available. It mirrors the Rust
``Router`` API exactly so ``GunbulletApp`` is agnostic to which one loaded:

* ``add(pattern, route_id)`` registers a route under an integer id.
* ``match(path)`` returns the matching ``(params, route_id)`` candidates in
  priority order -- static routes first, then dynamic routes in registration
  order -- or an empty list when nothing matches the path. The caller picks the
  first candidate whose handler allows the request method (so the 405-vs-404
  distinction is preserved by ``len(candidates)``).
"""

import re


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


class PyRouter:
    __slots__ = ("_static", "_dynamic")

    def __init__(self) -> None:
        self._static: dict[str, list[int]] = {}
        self._dynamic: list[tuple[re.Pattern[str], int]] = []

    def add(self, pattern: str, route_id: int) -> None:
        if "<" not in pattern:
            self._static.setdefault(pattern, []).append(route_id)
        else:
            self._dynamic.append((_compile_route(pattern), route_id))

    def match(self, path: str) -> list[tuple[dict[str, str], int]]:
        out: list[tuple[dict[str, str], int]] = [
            ({}, rid) for rid in self._static.get(path, ())
        ]
        for pattern, rid in self._dynamic:
            m = pattern.match(path)
            if m is not None:
                out.append((m.groupdict(), rid))
        return out
