"""Routing backend selection.

Prefer the compiled Rust radix router; fall back to the pure-Python
``PyRouter`` when the extension was not built (e.g. an sdist install or a
platform without a prebuilt wheel). Both expose the same ``add`` / ``match``
surface, so ``GunbulletApp`` does not care which one loaded.

Which backend won is reported at INFO on import, so an app can confirm whether
the Rust speedup is active (configure logging to see it, e.g.
``logging.basicConfig(level=logging.INFO)``).
"""

import logging

_logger = logging.getLogger("gunbullet")

try:
    from gunbullet._gunbullet_router import Router as Router  # type: ignore[no-redef]

    _logger.info("gunbullet: using the Rust radix router (speedup active)")
except ImportError:
    from gunbullet._router_py import PyRouter as Router  # type: ignore[no-redef]

    _logger.info("gunbullet: using the pure-Python router (Rust extension unavailable)")

__all__ = ["Router"]
