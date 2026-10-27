r"""一次可重放的 SSE 聊天教学演示，不调用真实模型。

从仓库根目录运行：
    .\backend\.venv\Scripts\python.exe .\learning\demos\sse_chat_walkthrough.py

FastAPI/StreamingResponse 和 HTTP 传输是真实执行的；模型输出用固定文本模拟。
客户端用 httpx 模拟浏览器逐块读取、UTF-8 解码、SSE 解析和界面文字累加。
本例使用自己生成的 LF 分隔格式，不是通用的生产级 SSE 解析器。
只绑定临时的 127.0.0.1 端口，演示结束后关闭，不使用 DeerFlow 配置或服务。
"""

import asyncio
import codecs
import json
import socket
import sys
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

QUESTION = "用一句话解释 await"
REPLY_PARTS = [
    "await 会等待操作完成，",
    "等待期间可以让其他任务运行，",
    "完成后继续后面的代码。",
]
STARTED = 0.0


def log(actor: str, message: str) -> None:
    elapsed = time.perf_counter() - STARTED
    print(f"{elapsed:5.2f}s [{actor}] {message}", flush=True)


async def model_stream():
    """模拟模型逐段输出；这里的 sleep 代替真实接口等待。"""
    for index, text in enumerate(REPLY_PARTS, start=1):
        log("模型模拟", f"等待第 {index} 段输出")
        await asyncio.sleep(0.4)
        log("模型模拟", f"yield 第 {index} 段：{text}")
        yield text


async def sse_events():
    """消费模型的文本片段，再交出 SSE 文本供响应框架消费。"""
    async for text in model_stream():
        data = json.dumps({"text": text}, ensure_ascii=False)
        frame = f"event: messages\ndata: {data}\n\n"
        log("SSE编码", f"交出一条 messages 事件：{frame!r}")
        yield frame


app = FastAPI()


@app.post("/demo/chat/stream")
async def chat_stream(request: Request):
    body = await request.json()
    log("接口", f"收到问题：{body['message']}")
    log("接口", "构造 StreamingResponse；此时模型生成器还没有执行")
    return StreamingResponse(sse_events(), media_type="text/event-stream")


async def traced_app(scope, receive, send):
    """只记录响应框架交给 HTTP 服务器的消息，不替代框架的消费逻辑。"""
    async def traced_send(message):
        if message["type"] == "http.response.start":
            log("HTTP", f"发送响应头，状态 {message['status']}")
        elif message["type"] == "http.response.body":
            if message.get("body"):
                log("HTTP", f"发送响应体片段：{len(message['body'])} 字节")
            if not message.get("more_body", False):
                log("HTTP", "结束本次 HTTP 响应")
        await send(message)

    await app(scope, receive, traced_send)


async def simulated_frontend(url: str) -> None:
    """aiter_bytes 类比浏览器持续 read；收到块后仍需缓冲并分出完整事件。"""
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    displayed_text = ""
    event_count = 0

    async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
        log("前端模拟", f"发送 POST {url}，问题：{QUESTION}")
        async with client.stream("POST", url, json={"message": QUESTION}) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            assert content_type.startswith("text/event-stream"), content_type
            log("前端模拟", f"收到响应头：{content_type}，开始逐块读取")

            async for raw in response.aiter_bytes():
                log("前端模拟", f"读到 {len(raw)} 字节；先解码、存入缓冲区")
                buffer += decoder.decode(raw)

                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    event_name = "message"
                    data_lines = []
                    for line in frame.splitlines():
                        name, separator, value = line.partition(":")
                        if not separator:
                            continue
                        if value.startswith(" "):
                            value = value[1:]
                        if name == "event":
                            event_name = value
                        elif name == "data":
                            data_lines.append(value)

                    if event_name == "messages" and data_lines:
                        payload = json.loads("\n".join(data_lines))
                        displayed_text += payload["text"]
                        event_count += 1
                        log("页面文字模拟", displayed_text)

            buffer += decoder.decode(b"", final=True)

    assert not buffer, f"存在未完整解析的内容：{buffer!r}"
    assert event_count == len(REPLY_PARTS), event_count
    assert displayed_text == "".join(REPLY_PARTS), displayed_text
    log("核验", f"收到 {event_count} 个完整事件，累加文字与预期一致")


async def main() -> None:
    global STARTED
    STARTED = time.perf_counter()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as demo_socket:
        demo_socket.bind(("127.0.0.1", 0))
        demo_socket.listen(128)
        demo_socket.setblocking(False)
        demo_port = demo_socket.getsockname()[1]

        server = uvicorn.Server(
            uvicorn.Config(
                traced_app,
                host="127.0.0.1",
                port=demo_port,
                loop="asyncio",
                lifespan="off",
                log_level="critical",
                access_log=False,
            )
        )
        server_task = asyncio.create_task(server.serve(sockets=[demo_socket]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if server_task.done():
                        await server_task
                        raise RuntimeError("临时演示服务器未启动")
                    await asyncio.sleep(0.01)

            await simulated_frontend(f"http://127.0.0.1:{demo_port}/demo/chat/stream")
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=5)

    log("清理", "临时 HTTP 服务和端口已关闭")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
