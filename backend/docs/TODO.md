# TODO List

## Completed Features

- [x] Launch the sandbox only after the first file system or bash tool is called
- [x] Add Clarification Process for the whole process
- [x] Implement Context Summarization Mechanism to avoid context explosion
- [x] Integrate MCP (Model Context Protocol) for extensible tools
- [x] Add file upload support with automatic document conversion
- [x] Implement automatic thread title generation
- [x] Add Plan Mode with TodoList middleware
- [x] Add vision model support with ViewImageMiddleware
- [x] Skills system with SKILL.md format

## Planned Features

- [ ] Pooling the sandbox resources to reduce the number of sandbox containers
- [ ] Add authentication/authorization layer
- [ ] Implement rate limiting
- [ ] Add metrics and monitoring
- [ ] Support for more document formats in upload
- [ ] Skill marketplace / remote skill installation
- [ ] Optimize async concurrency in agent hot path (IM channels multi-task scenario)
  - Replace `time.sleep(5)` with `asyncio.sleep()` in `src/tools/builtins/task_tool.py` (subagent polling)
  - Replace `subprocess.run()` with `asyncio.create_subprocess_shell()` in `src/sandbox/local/local_sandbox.py`
  - Replace sync `requests` with `httpx.AsyncClient` in community tools (tavily, jina_ai, firecrawl, infoquest, image_search)
  - Replace sync `model.invoke()` with async `model.ainvoke()` in title_middleware and memory updater
  - Consider `asyncio.to_thread()` wrapper for remaining blocking file I/O
  - For production: use `langgraph up` (multi-worker) instead of `langgraph dev` (single-worker)

## Resolved Issues

- [x] Make sure that no duplicated files in `state.artifacts`
- [x] Long thinking but with empty content (answer inside thinking process)
