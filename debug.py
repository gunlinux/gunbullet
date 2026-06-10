import asyncio
import uvicorn

from app import create_app_asgi

app_asgi = create_app_asgi()


async def main():
    config = uvicorn.Config("main:app_asgi", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
