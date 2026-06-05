"""
Simple aiohttp Web Application

The same app as app/wsgi.py (routes /, /about, /contact, else 404), but built
on aiohttp's own HTTP server/framework instead of a bare WSGI/ASGI/RSGI
callable. Included for comparison: unlike the other modules, aiohttp owns the
event loop and the server, so there is no `application(environ, ...)`-style
callable a third-party server imports — you hand a `web.Application` to
aiohttp's own runner.

Handlers receive a `web.Request` and return a `web.Response`; aiohttp sets
Content-Length for us when the body is passed as `text`/`body`.

Run it:
    uv run python -m aiohttp.web app.aiohttp_server:create_app
"""

import logging
import time

from aiohttp import web

logger = logging.getLogger("aiohttp_server.access")


@web.middleware
async def access_log_middleware(request: web.Request, handler) -> web.Response:
    """Log one line per request: method, path, status, and duration in ms.

    Wraps every handler, so it logs both matched routes and the catch-all 404.
    """
    start = time.perf_counter()
    response = await handler(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        '%s %s "%s %s" %d %dB %.2fms',
        request.remote,
        request.method,
        request.path,
        request.query_string or "-",
        response.status,
        response.content_length or 0,
        elapsed_ms,
    )
    return response


async def home_page(request: web.Request) -> web.Response:
    """Home page handler"""
    method = request.method
    path = request.path
    query_string = request.query_string

    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple aiohttp App</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            .info {{ background: #f0f0f0; padding: 15px; margin: 15px 0; border-radius: 5px; }}
            nav {{ margin: 20px 0; }}
            nav a {{ margin-right: 15px; color: #007acc; text-decoration: none; }}
            nav a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h1>Welcome to Simple aiohttp App</h1>

        <div class="info">
            <h3>Request Information:</h3>
            <p><strong>Method:</strong> {method}</p>
            <p><strong>Path:</strong> {path}</p>
            <p><strong>Query String:</strong> {query_string}</p>
        </div>

        <nav>
            <a href="/">Home</a>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
        </nav>

        <p>This is a simple aiohttp web application demonstrating basic concepts.</p>
    </body>
    </html>
    """

    return web.Response(text=body, content_type="text/html", charset="utf-8")


async def about_page(request: web.Request) -> web.Response:
    """About page handler"""
    body = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>About - Simple aiohttp App</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            nav { margin: 20px 0; }
            nav a { margin-right: 15px; color: #007acc; text-decoration: none; }
            nav a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>About This Application</h1>

        <p>This is a simple aiohttp web application that demonstrates:</p>
        <ul>
            <li>aiohttp application interface</li>
            <li>Basic URL routing</li>
            <li>Request/Response handling</li>
            <li>HTML generation</li>
        </ul>

        <nav>
            <a href="/">Home</a>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
        </nav>
    </body>
    </html>
    """

    return web.Response(text=body, content_type="text/html", charset="utf-8")


async def contact_page(request: web.Request) -> web.Response:
    """Contact page handler"""
    body = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Contact - Simple aiohttp App</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            nav { margin: 20px 0; }
            nav a { margin-right: 15px; color: #007acc; text-decoration: none; }
            nav a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>Contact Us</h1>

        <p>Get in touch with us:</p>
        <p><strong>Email:</strong> contact@example.com</p>
        <p><strong>Phone:</strong> (555) 123-4567</p>

        <nav>
            <a href="/">Home</a>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
        </nav>
    </body>
    </html>
    """

    return web.Response(text=body, content_type="text/html", charset="utf-8")


async def not_found_page(request: web.Request) -> web.Response:
    """404 error page handler"""
    path = request.path

    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page Not Found</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; text-align: center; }}
            .error {{ color: #dc3545; }}
            nav {{ margin: 20px 0; }}
            nav a {{ margin-right: 15px; color: #007acc; text-decoration: none; }}
            nav a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h1 class="error">404 - Page Not Found</h1>
        <p>The page <code>{path}</code> could not be found.</p>

        <nav>
            <a href="/">Home</a>
            <a href="/about">About</a>
            <a href="/contact">Contact</a>
        </nav>
    </body>
    </html>
    """

    return web.Response(
        text=body, status=404, content_type="text/html", charset="utf-8"
    )


def create_app() -> web.Application:
    """Build the aiohttp application with the same routes as app/wsgi.py."""
    app = web.Application(middlewares=[access_log_middleware])
    app.add_routes(
        [
            web.get("/", home_page),
            web.get("/about", about_page),
            web.get("/contact", contact_page),
            # Catch-all for any other path so we serve our own 404 page.
            web.route("*", "/{tail:.*}", not_found_page),
        ]
    )
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    web.run_app(create_app())
