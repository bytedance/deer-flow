# TODO 列表

## 已完成功能

- [x] 仅在首次调用文件系统或 bash 工具后再启动沙箱
- [x] 为全流程增加澄清（Clarification）机制
- [x] 实现上下文摘要机制，避免上下文膨胀
- [x] 集成 MCP（Model Context Protocol）以扩展工具能力
- [x] 增加文件上传支持并自动转换文档
- [x] 实现会话标题自动生成
- [x] 增加 Plan Mode 与 TodoList 中间件
- [x] 通过 ViewImageMiddleware 增加视觉模型支持
- [x] 支持 SKILL.md 格式的技能系统
- [x] 在 `packages/harness/deerflow/tools/builtins/task_tool.py`（subagent 轮询）中将 `time.sleep(5)` 替换为 `asyncio.sleep()`

## 计划功能

- [ ] 池化沙箱资源，减少沙箱容器数量
- [ ] 增加认证/鉴权层
- [ ] 实现限流
- [ ] 增加指标与监控
- [ ] 上传支持更多文档格式
- [ ] 技能市场 / 远程技能安装
- [ ] 优化 agent 热路径中的异步并发（IM channels 多任务场景）
- [ ] 在 `packages/harness/deerflow/sandbox/local/local_sandbox.py` 中将 `subprocess.run()` 替换为 `asyncio.create_subprocess_shell()`
  - 在 community tools（tavily、jina_ai、firecrawl、infoquest、image_search）中将同步 `requests` 替换为 `httpx.AsyncClient`
  - [x] 在 title_middleware 与 memory updater 中将同步 `model.invoke()` 替换为异步 `model.ainvoke()`
  - 考虑对剩余阻塞型文件 I/O 使用 `asyncio.to_thread()` 包装
  - 生产环境使用 `langgraph up`（多 worker）替代 `langgraph dev`（单 worker）

## 已解决问题

- [x] 确保 `state.artifacts` 中不存在重复文件
- [x] 长时间思考但 content 为空（答案出现在思考过程内）
