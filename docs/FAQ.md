# FAQ

## Table of Contents

- [Where's the name DeerFlow come from?](#wheres-the-name-deerflow-come-from)
- [Which models does DeerFlow support?](#which-models-does-deerflow-support)
- [How do I view complete model output?](#how-do-i-view-complete-model-output)
- [How do I enable debug logging?](#how-do-i-enable-debug-logging)
- [How do I troubleshoot issues?](#how-do-i-troubleshoot-issues)

## Where's the name DeerFlow come from?

DeerFlow is short for **D**eep **E**xploration and **E**fficient **R**esearch **Flow**. It is named after the deer, which is a symbol of gentleness and elegance. We hope DeerFlow can bring a gentle and elegant deep research experience to you.

## Which models does DeerFlow support?

Please refer to the [Configuration Guide](configuration_guide.md) for more details.

## How do I view complete model output?

If you want to see the complete model output, including system prompts, tool calls, and LLM responses:

1. **Enable debug logging** by setting `DEBUG=True` in your `.env` file

2. **Enable LangChain verbose logging** by adding these to your `.env`:

   ```bash
   LANGCHAIN_VERBOSE=true
   LANGCHAIN_DEBUG=true
   ```

3. **Use LangSmith tracing** for visual debugging (recommended for production):

   ```bash
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY="your-api-key"
   LANGSMITH_PROJECT="your-project-name"
   ```

For detailed instructions, see the [Debugging Guide](DEBUGGING.md).

## How do I enable debug logging?

To enable debug logging:

1. Open your `.env` file
2. Set `DEBUG=True`
3. Restart your application

For Docker Compose:

```bash
docker compose restart
```

For development:

```bash
uv run main.py
```

You'll now see detailed logs including:

- System prompts sent to LLMs
- Model responses
- Tool execution details
- Workflow state transitions

See the [Debugging Guide](DEBUGGING.md) for more options.

## How do I troubleshoot issues?

When encountering issues:

1. **Check the logs**: Enable debug logging as described above
2. **Review configuration**: Ensure your `.env` and `conf.yaml` are correct
3. **Check existing issues**: Search [GitHub Issues](https://github.com/bytedance/deer-flow/issues) for similar problems
4. **Enable verbose logging**: Use `LANGCHAIN_VERBOSE=true` for detailed output
5. **Use LangSmith**: For visual debugging, enable LangSmith tracing

For Docker-specific issues:

```bash
# View logs
docker compose logs -f

# Check container status
docker compose ps

# Restart services
docker compose restart
```

For more detailed troubleshooting steps, see the [Debugging Guide](DEBUGGING.md).
