from typing import TYPE_CHECKING, Protocol

import httpx2 as httpx

from gunbullet.testclient import TestClient
from gunbullet import GunbulletApp

if TYPE_CHECKING:

    class TestClientFactory(Protocol):  # pragma: no cover
        def __call__(
            self,
            app: GunbulletApp,
            base_url: str = "http://testserver",
            raise_server_exceptions: bool = True,
            root_path: str = "",
            cookies: httpx._types.CookieTypes | None = None,
            headers: dict[str, str] | None = None,
            follow_redirects: bool = True,
            client: tuple[str, int] = ("testclient", 50000),
        ) -> TestClient: ...
else:  # pragma: no cover

    class TestClientFactory:
        __test__ = False
