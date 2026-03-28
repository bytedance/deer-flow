# 2026-03-27-01
## 修复404 问题，下面的链接访问报 404
curl 'http://localhost:3000/api/models' \
  -H 'Accept: */*' \
  -H 'Accept-Language: zh-CN,zh;q=0.9,en;q=0.8' \
  -H 'Cache-Control: no-cache' \
  -H 'Connection: keep-alive' \
  -b 'locale=zh-CN; x-pw-session-id=13825b46-ecb9-4168-bf44-2e25e0846a1e; theme_mode=light; __next_hmr_refresh_hash__=75; sidebar_state=true' \
  -H 'Pragma: no-cache' \
  -H 'Referer: http://localhost:3000/workspace/chats/new' \
  -H 'Sec-Fetch-Dest: empty' \
  -H 'Sec-Fetch-Mode: cors' \
  -H 'Sec-Fetch-Site: same-origin' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36' \
  -H 'sec-ch-ua: "Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"' \
  -H 'sec-ch-ua-mobile: ?0' \
  -H 'sec-ch-ua-platform: "macOS"'

curl 'http://localhost:3000/api/langgraph/threads/search' \
  -H 'Accept: */*' \
  -H 'Accept-Language: zh-CN,zh;q=0.9,en;q=0.8' \
  -H 'Cache-Control: no-cache' \
  -H 'Connection: keep-alive' \
  -b 'locale=zh-CN; x-pw-session-id=13825b46-ecb9-4168-bf44-2e25e0846a1e; theme_mode=light; __next_hmr_refresh_hash__=75; sidebar_state=true' \
  -H 'Origin: http://localhost:3000' \
  -H 'Pragma: no-cache' \
  -H 'Referer: http://localhost:3000/workspace/chats/new' \
  -H 'Sec-Fetch-Dest: empty' \
  -H 'Sec-Fetch-Mode: cors' \
  -H 'Sec-Fetch-Site: same-origin' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36' \
  -H 'content-type: application/json' \
  -H 'sec-ch-ua: "Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"' \
  -H 'sec-ch-ua-mobile: ?0' \
  -H 'sec-ch-ua-platform: "macOS"' \
  --data-raw '{"limit":50,"offset":0,"sort_by":"updated_at","sort_order":"desc","select":["thread_id","updated_at","values"]}'

  - **fixed** 用端口 2026 而不是 3000 访问

# 2026-03-27-02
## 运行创建聊天报错
运行 http://ido.modelturbo.com:2026/workspace/chats/new
- 网页报错“Application error: a client-side exception has occurred while loading ido.modelturbo.com (see the browser console for more information).“
- 控制台错误日志如下：
  GET http://ido.modelturbo.com:2026/images/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98.jpg net::ERR_CONTENT_LENGTH_MISMATCH 200 (OK)
(index):1  GET http://ido.modelturbo.com:2026/images/ad76c455-5bf9-4335-8517-fc03834ab828.jpg net::ERR_CONTENT_LENGTH_MISMATCH 200 (OK)
(index):1  GET http://ido.modelturbo.com:2026/images/3823e443-4e2b-4679-b496-a9506eae462b.jpg net::ERR_CONTENT_LENGTH_MISMATCH 200 (OK)
(index):1  GET http://ido.modelturbo.com:2026/images/4f3e55ee-f853-43db-bfb3-7d1a411f03cb.jpg net::ERR_CONTENT_LENGTH_MISMATCH 200 (OK)
turbopack-9592eda410a7d41f.js:4  GET http://ido.modelturbo.com:2026/_next/static/chunks/0b42c77c3d0a776c.js net::ERR_INCOMPLETE_CHUNKED_ENCODING 200 (OK)
(anonymous) @ turbopack-9592eda410a7d41f.js:4
loadChunkCached @ turbopack-9592eda410a7d41f.js:4
E @ turbopack-9592eda410a7d41f.js:1
R.L @ turbopack-9592eda410a7d41f.js:1
c @ 368333daeb3f616f.js:1
(anonymous) @ 368333daeb3f616f.js:1
t @ 368333daeb3f616f.js:1
Promise.then
ei @ 368333daeb3f616f.js:1
(anonymous) @ 368333daeb3f616f.js:1
Promise.then
r.createFromFetch @ 368333daeb3f616f.js:1
R @ 368333daeb3f616f.js:1
b @ 368333daeb3f616f.js:1
A @ 368333daeb3f616f.js:1
w @ 368333daeb3f616f.js:1
p @ 368333daeb3f616f.js:1
d @ 368333daeb3f616f.js:1
y @ 368333daeb3f616f.js:1
c @ 368333daeb3f616f.js:2
action @ 368333daeb3f616f.js:2
g @ 368333daeb3f616f.js:2
(anonymous) @ 368333daeb3f616f.js:2
dispatch @ 368333daeb3f616f.js:2
o @ 368333daeb3f616f.js:1
i @ 368333daeb3f616f.js:1
m @ 368333daeb3f616f.js:2
(anonymous) @ 09e4bc476f954631.js:1
H @ cf0f8c398d9abb9f.js:1
(anonymous) @ 09e4bc476f954631.js:1
onClick @ 09e4bc476f954631.js:1
sY @ 5d91dc0d7375642e.js:1
(anonymous) @ 5d91dc0d7375642e.js:1
tD @ 5d91dc0d7375642e.js:1
s3 @ 5d91dc0d7375642e.js:1
fC @ 5d91dc0d7375642e.js:1
fP @ 5d91dc0d7375642e.js:1
turbopack-9592eda410a7d41f.js:1 Uncaught ChunkLoadError: Failed to load chunk /_next/static/chunks/0b42c77c3d0a776c.js from module 561716
    at turbopack-9592eda410a7d41f.js:1:5989
(anonymous) @ turbopack-9592eda410a7d41f.js:1
Promise.catch
E @ turbopack-9592eda410a7d41f.js:1
R.L @ turbopack-9592eda410a7d41f.js:1
c @ 368333daeb3f616f.js:1
(anonymous) @ 368333daeb3f616f.js:1
t @ 368333daeb3f616f.js:1
Promise.then
ei @ 368333daeb3f616f.js:1
(anonymous) @ 368333daeb3f616f.js:1
Promise.then
r.createFromFetch @ 368333daeb3f616f.js:1
R @ 368333daeb3f616f.js:1
b @ 368333daeb3f616f.js:1
A @ 368333daeb3f616f.js:1
w @ 368333daeb3f616f.js:1
p @ 368333daeb3f616f.js:1
d @ 368333daeb3f616f.js:1
y @ 368333daeb3f616f.js:1
c @ 368333daeb3f616f.js:2
action @ 368333daeb3f616f.js:2
g @ 368333daeb3f616f.js:2
(anonymous) @ 368333daeb3f616f.js:2
dispatch @ 368333daeb3f616f.js:2
o @ 368333daeb3f616f.js:1
i @ 368333daeb3f616f.js:1
m @ 368333daeb3f616f.js:2
(anonymous) @ 09e4bc476f954631.js:1
H @ cf0f8c398d9abb9f.js:1
(anonymous) @ 09e4bc476f954631.js:1
onClick @ 09e4bc476f954631.js:1
sY @ 5d91dc0d7375642e.js:1
(anonymous) @ 5d91dc0d7375642e.js:1
tD @ 5d91dc0d7375642e.js:1
s3 @ 5d91dc0d7375642e.js:1
fC @ 5d91dc0d7375642e.js:1
fP @ 5d91dc0d7375642e.js:1

# 2026-03-27-03
## 运行这个报错500
curl 'http://ido.raisingai.com:2026/api/langgraph/threads/129195c3-0fce-4a40-b6d3-b53755b28f69/history' \
  -H 'Accept: */*' \
  -H 'Accept-Language: zh-CN,zh;q=0.9,en;q=0.8' \
  -H 'Cache-Control: no-cache' \
  -b 'locale=zh-CN' \
  -H 'Origin: http://ido.raisingai.com:2026' \
  -H 'Pragma: no-cache' \
  -H 'Proxy-Connection: keep-alive' \
  -H 'Referer: http://ido.raisingai.com:2026/workspace/chats/129195c3-0fce-4a40-b6d3-b53755b28f69' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36' \
  -H 'content-type: application/json' \
  --data-raw '{"limit":1}' \
  --insecure

  日志如下
  2026-03-27T13:17:09.505854Z [error    ] POST /threads/129195c3-0fce-4a40-b6d3-b53755b28f69/history 500 0ms [langgraph_api.server] api_variant=local_dev langgraph_api_version=0.7.65 latency_ms=0 method=POST path=/threads/{thread_id}/history path_params={'thread_id': '129195c3-0fce-4a40-b6d3-b53755b28f69'} proto=1.1 query_string= req_header={} request_id=bbbfe1ba-7d3d-449e-a268-48d122b39511 res_header={} route=/threads/{thread_id}/history status=500 thread_name=MainThread
2026-03-27T13:17:09.506409Z [error    ] Exception in ASGI application
 [uvicorn.error] api_variant=local_dev langgraph_api_version=0.7.65 thread_name=MainThread
Traceback (most recent call last):
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/uvicorn/protocols/http/httptools_impl.py", line 416, in run_asgi
    result = await app(  # type: ignore[func-returns-value]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/uvicorn/middleware/proxy_headers.py", line 60, in __call__
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/applications.py", line 107, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/errors.py", line 186, in __call__
    raise exc
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/errors.py", line 164, in __call__
    await self.app(scope, receive, _send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 191, in __call__
    with recv_stream, send_stream, collapse_excgroups():
                                   ^^^^^^^^^^^^^^^^^^^^
  File "/home/idobot/.local/share/uv/python/cpython-3.12.12-linux-x86_64-gnu/lib/python3.12/contextlib.py", line 158, in __exit__
    self.gen.throw(value)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/_utils.py", line 85, in collapse_excgroups
    raise exc
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 193, in __call__
    response = await self.dispatch_func(request, call_next)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/middleware/private_network.py", line 50, in dispatch
    response = await call_next(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 168, in call_next
    raise app_exc from app_exc.__cause__ or app_exc.__context__
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/base.py", line 144, in coro
    await self.app(scope, receive_or_disconnect, send_no_error)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/cors.py", line 93, in __call__
    await self.simple_response(scope, receive, send, request_headers=headers)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/cors.py", line 144, in simple_response
    await self.app(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/middleware/http_logger.py", line 80, in __call__
    raise exc
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/middleware/http_logger.py", line 74, in __call__
    await self.app(scope, inner_receive, inner_send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/middleware/request_id.py", line 35, in __call__
    await self.app(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/exceptions.py", line 63, in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/routing.py", line 716, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/routing.py", line 736, in app
    await route.handle(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/routing.py", line 462, in handle
    await self.app(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/auth/middleware.py", line 53, in __call__
    return await super().__call__(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/middleware/authentication.py", line 48, in __call__
    await self.app(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/routing.py", line 716, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/routing.py", line 736, in app
    await route.handle(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/route.py", line 166, in handle
    return await super().handle(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/routing.py", line 290, in handle
    await self.app(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/route.py", line 57, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/route.py", line 50, in app
    response: ASGIApp = await func(request)
                        ^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_runtime_inmem/retry.py", line 27, in wrapper
    return await func(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/api/threads.py", line 369, in get_thread_history_post
    for c in await Threads.State.list(
             ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_runtime_inmem/ops.py", line 1877, in list
    async with get_graph(
               ^^^^^^^^^^
  File "/home/idobot/.local/share/uv/python/cpython-3.12.12-linux-x86_64-gnu/lib/python3.12/contextlib.py", line 210, in __aenter__
    return await anext(self.gen)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/graph.py", line 240, in get_graph
    value = invoke_factory(value, graph_id, config, server_runtime)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/.venv/lib/python3.12/site-packages/langgraph_api/_factory_utils.py", line 184, in invoke_factory
    return value(**graph_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/packages/harness/deerflow/agents/lead_agent/agent.py", line 286, in make_lead_agent
    agent_model_name = agent_config.model if agent_config and agent_config.model else _resolve_model_name()
                                                                                      ^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/packages/harness/deerflow/agents/lead_agent/agent.py", line 28, in _resolve_model_name
    app_config = get_app_config()
                 ^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/packages/harness/deerflow/config/app_config.py", line 276, in get_app_config
    resolved_path = AppConfig.resolve_config_path()
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/data/projects/solution_agent/backend/packages/harness/deerflow/config/app_config.py", line 71, in resolve_config_path
    raise FileNotFoundError("`config.yaml` file not found at the current directory nor its parent directory")
FileNotFoundError: `config.yaml` file not found at the current directory nor its parent directory

# 2026-03-27-04
1. 应用基础信息
App ID：cli_a94c3b658db89bde
App Secret:uTpogDDABYMW7DjhOLjkreRJn5W0lkIl

2. 测试环境与生产环境各自的 redirect_uri 为 跳转前的页面的 url

3. 在调试模式下面时，所有页面加入
<script src='https://lf-package-cn.feishucdn.com/obj/feishu-static/op/fe/devtools_frontend/remote-debug-0.0.1-alpha.6.js'></script>

# 2026-03-28-01
## 集成飞书的登录
- 参考 /Users/edy/greatfeel/IDO/projects/temp/web_app_with_auth/python 的实现
- 仍然用现在的 python 的 API 框架，不要用 flask

# Archives(Just Ignore)
## 无法设计你的智能体，打开下面的页面报内部错误
http://ido.modelturbo.com:2026/workspace/agents/new



