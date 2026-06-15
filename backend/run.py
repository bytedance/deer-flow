"""启动脚本：在 uvicorn 之前设置 WindowsSelectorEventLoopPolicy"""
import asyncio
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    config = uvicorn.Config(
        app="app.gateway.app:app",
        host="127.0.0.1",
        port=8001,
        reload=False,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
