"""
Simple ASGI Web Application

A basic ASGI application demonstrating:
- ASGI interface: application(scope, receive, send)
- Request handling and routing
- HTML response generation
"""

import json

import msgspec
import ujson

from app.schema import marshmallow_schema, msgspec_schema, pydantic_schema
from app.users import Users


async def application(scope, receive, send):
    """
    Main ASGI application with basic routing

    Args:
        scope: Dict with connection/request info (type, path, method, ...)
        receive: Awaitable to receive ASGI events from the server
        send: Awaitable to send ASGI events back to the server
    """
    # Handle the lifespan protocol (startup/shutdown) so servers don't hang.
    if scope["type"] == "lifespan":
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                print("lifespan handler")
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    # Drain the request body events (we don't use the body, but must consume them).
    more_body = True
    while more_body:
        event = await receive()
        more_body = event.get("more_body", False)

    path = scope["path"]

    # Simple routing
    if path == "/":
        await home_page(scope, receive, send)
    elif path == "/about":
        await about_page(scope, receive, send)
    elif path == "/contact":
        await contact_page(scope, receive, send)
    elif path == "/api/pydantic":
        await api_pydantic_page(scope, receive, send)
    elif path == "/api/marshmallow":
        await api_marshmallow_page(scope, receive, send)
    elif path == "/api/marshmallow-ujson":
        await api_marshmallow_ujson_page(scope, receive, send)
    elif path == "/api/msgspec":
        await api_msgspec_page(scope, receive, send)
    else:
        await not_found_page(scope, receive, send)


async def send_html(send, status, body):
    """Encode an HTML body and emit the ASGI response events."""
    response_bytes = body.encode("utf-8")
    headers = [
        (b"content-type", b"text/html; charset=utf-8"),
        (b"content-length", str(len(response_bytes)).encode("utf-8")),
    ]

    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": response_bytes,
        }
    )


async def send_json(send, status, body):
    """Emit a JSON response. ``body`` is already JSON-encoded bytes."""
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("utf-8")),
    ]
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body,
        }
    )


async def home_page(scope, receive, send):
    """Home page handler"""
    method = scope["method"]
    path = scope["path"]
    query_string = scope.get("query_string", b"").decode("utf-8")

    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple ASGI App</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            .info {{ background: #f0f0f0; padding: 15px; margin: 15px 0; border-radius: 5px; }}
            nav {{ margin: 20px 0; }}
            nav a {{ margin-right: 15px; color: #007acc; text-decoration: none; }}
            nav a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h1>Welcome to Simple ASGI App</h1>

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

        <p>This is a simple ASGI web application demonstrating basic concepts.</p>
    </body>
    </html>
    """

    await send_html(send, 200, body)


async def about_page(scope, receive, send):
    """About page handler"""
    body = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>About - Simple ASGI App</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            nav { margin: 20px 0; }
            nav a { margin-right: 15px; color: #007acc; text-decoration: none; }
            nav a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>About This Application</h1>

        <p>This is a simple ASGI web application that demonstrates:</p>
        <ul>
            <li>ASGI application interface</li>
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

    await send_html(send, 200, body)


async def contact_page(scope, receive, send):
    """Contact page handler"""
    body = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Contact - Simple ASGI App</title>
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

    await send_html(send, 200, body)


async def not_found_page(scope, receive, send):
    """404 error page handler"""
    path = scope.get("path", "/")

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

    await send_html(send, 404, body)


async def api_pydantic_page(scope, receive, send):
    """API handler: validate users.json with pydantic and serialize back to JSON."""
    payload = json.loads(Users.get_users())
    response = pydantic_schema.UsersResponse.model_validate(payload)
    body = response.model_dump_json().encode("utf-8")

    await send_json(send, 200, body)


async def api_marshmallow_page(scope, receive, send):
    """API handler: validate users.json with marshmallow and serialize back to JSON."""
    schema = marshmallow_schema.UsersResponse()
    payload = json.loads(Users.get_users())
    data = schema.load(payload)
    body = json.dumps(schema.dump(data)).encode("utf-8")

    await send_json(send, 200, body)


async def api_marshmallow_ujson_page(scope, receive, send):
    """Same as the marshmallow handler, but using ujson for parse/serialize.

    Isolates how much of that path is the json encode/decode (swappable) versus
    marshmallow's own pure-Python load/dump (the dominant, unswappable cost).
    """
    schema = marshmallow_schema.UsersResponse()
    payload = ujson.loads(Users.get_users())
    data = schema.load(payload)
    body = ujson.dumps(schema.dump(data)).encode("utf-8")

    await send_json(send, 200, body)


async def api_msgspec_page(scope, receive, send):
    """API handler: validate users.json with msgspec and serialize back to JSON."""
    raw = Users.get_users()
    response = msgspec.json.decode(raw, type=msgspec_schema.UsersResponse)
    body = msgspec.json.encode(response)

    await send_json(send, 200, body)
