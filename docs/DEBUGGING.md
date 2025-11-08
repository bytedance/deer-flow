# Debugging Guide

This guide helps you debug DeerFlow workflows, view model outputs, and troubleshoot common issues.

## Table of Contents

- [Viewing Model Output](#viewing-model-output)
- [Debug Logging Configuration](#debug-logging-configuration)
- [LangChain Verbose Logging](#langchain-verbose-logging)
- [LangSmith Tracing](#langsmith-tracing)
- [Docker Compose Debugging](#docker-compose-debugging)
- [Common Issues](#common-issues)

## Viewing Model Output

When you need to see the complete model output, including tool calls and internal reasoning, you have several options:

### 1. Enable Debug Logging

Set `DEBUG=True` in your `.env` file or configuration:

```bash
DEBUG=True
```

This enables debug-level logging throughout the application, showing detailed information about:
- System prompts sent to LLMs
- Model responses
- Tool calls and results
- Workflow state transitions

### 2. Enable LangChain Verbose Logging

Add these environment variables to your `.env` file for detailed LangChain output:

```bash
# Enable verbose logging for LangChain
LANGCHAIN_VERBOSE=true
LANGCHAIN_DEBUG=true
```

This will show:
- Chain execution steps
- LLM input/output for each call
- Tool invocations
- Intermediate results

### 3. Enable LangSmith Tracing (Recommended for Production)

For advanced debugging and visualization, configure LangSmith integration:

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
LANGSMITH_API_KEY="your-api-key"
LANGSMITH_PROJECT="your-project-name"
```

LangSmith provides:
- Visual trace of workflow execution
- Performance metrics
- Token usage statistics
- Error tracking
- Comparison between runs

To get started with LangSmith:
1. Sign up at [LangSmith](https://smith.langchain.com/)
2. Create a project
3. Copy your API key
4. Add the configuration to your `.env` file

## Debug Logging Configuration

### Log Levels

DeerFlow uses Python's standard logging levels:

- **DEBUG**: Detailed diagnostic information
- **INFO**: General informational messages
- **WARNING**: Warning messages
- **ERROR**: Error messages
- **CRITICAL**: Critical errors

### Viewing Logs

**Development mode (console):**
```bash
uv run main.py
```

Logs will be printed to the console.

**Docker Compose:**
```bash
# View logs from all services
docker compose logs -f

# View logs from backend only
docker compose logs -f backend

# View logs with timestamps
docker compose logs -f --timestamps
```

## LangChain Verbose Logging

### What It Shows

When `LANGCHAIN_VERBOSE=true` is enabled, you'll see output like:

```
> Entering new AgentExecutor chain...
Thought: I need to search for information about quantum computing
Action: web_search
Action Input: "quantum computing basics 2024"

Observation: [Search results...]

Thought: I now have enough information to answer
Final Answer: ...
```

### Configuration Options

```bash
# Basic verbose mode
LANGCHAIN_VERBOSE=true

# Full debug mode with internal details
LANGCHAIN_DEBUG=true

# Both (recommended for debugging)
LANGCHAIN_VERBOSE=true
LANGCHAIN_DEBUG=true
```

## LangSmith Tracing

### Setup

1. **Create a LangSmith account**: Visit [smith.langchain.com](https://smith.langchain.com)

2. **Get your API key**: Navigate to Settings → API Keys

3. **Configure environment variables**:
```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
LANGSMITH_API_KEY="lsv2_pt_..."
LANGSMITH_PROJECT="deerflow-debug"
```

4. **Restart your application**

### Features

- **Visual traces**: See the entire workflow execution as a graph
- **Performance metrics**: Identify slow operations
- **Token tracking**: Monitor LLM token usage
- **Error analysis**: Quickly identify failures
- **Comparison**: Compare different runs side-by-side

### Viewing Traces

1. Run your workflow as normal
2. Visit [smith.langchain.com](https://smith.langchain.com)
3. Select your project
4. View traces in the "Traces" tab

## Docker Compose Debugging

### Update docker-compose.yml

Add debug environment variables to your `docker-compose.yml`:

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      # Debug settings
      - DEBUG=True
      - LANGCHAIN_VERBOSE=true
      - LANGCHAIN_DEBUG=true

      # LangSmith (optional)
      - LANGSMITH_TRACING=true
      - LANGSMITH_ENDPOINT=https://api.smith.langchain.com
      - LANGSMITH_API_KEY=${LANGSMITH_API_KEY}
      - LANGSMITH_PROJECT=${LANGSMITH_PROJECT}
```

### View Detailed Logs

```bash
# Start with verbose output
docker compose up

# Or in detached mode and follow logs
docker compose up -d
docker compose logs -f backend
```

### Common Docker Commands

```bash
# View logs from last 100 lines
docker compose logs --tail=100 backend

# View logs with timestamps
docker compose logs -f --timestamps

# Check container status
docker compose ps

# Restart services
docker compose restart backend
```

## Common Issues

### Issue: "Log information doesn't show complete content"

**Solution**: Enable debug logging as described above:
```bash
DEBUG=True
LANGCHAIN_VERBOSE=true
LANGCHAIN_DEBUG=true
```

### Issue: "Can't see system prompts"

**Solution**: Debug logging will show system prompts. Look for log entries like:
```
[INFO] System Prompt:
You are DeerFlow, a friendly AI assistant...
```

### Issue: "Want to see token usage"

**Solution**: Enable LangSmith tracing or check model responses in verbose mode:
```bash
LANGCHAIN_VERBOSE=true
```

### Issue: "Need to debug specific nodes"

**Solution**: Add custom logging in specific nodes. For example, in `src/graph/nodes.py`:
```python
import logging
logger = logging.getLogger(__name__)

def my_node(state, config):
    logger.debug(f"Node input: {state}")
    # ... your code ...
    logger.debug(f"Node output: {result}")
    return result
```

### Issue: "Logs are too verbose"

**Solution**: Adjust log level for specific modules:
```python
# In your code
logging.getLogger('langchain').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
```

## Performance Debugging

### Measure Execution Time

Enable LangSmith or add timing logs:

```python
import time
start = time.time()
result = some_function()
logger.info(f"Execution time: {time.time() - start:.2f}s")
```

### Monitor Token Usage

With LangSmith enabled, token usage is automatically tracked. Alternatively, check model responses:

```bash
LANGCHAIN_VERBOSE=true
```

Look for output like:
```
Tokens Used: 150
  Prompt Tokens: 100
  Completion Tokens: 50
```

## Additional Resources

- [LangSmith Documentation](https://docs.smith.langchain.com/)
- [LangGraph Debugging](https://langchain-ai.github.io/langgraph/how-tos/debugging/)
- [Configuration Guide](./configuration_guide.md)
- [API Documentation](./API.md)

## Getting Help

If you're still experiencing issues:

1. Check existing [GitHub Issues](https://github.com/bytedance/deer-flow/issues)
2. Enable debug logging and LangSmith tracing
3. Collect relevant log output
4. Create a new issue with:
   - Description of the problem
   - Steps to reproduce
   - Log output
   - Configuration (without sensitive data)
