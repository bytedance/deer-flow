# Configuration Guide

## Quick Settings

Copy the `conf.yaml.example` file to `conf.yaml` and modify the configurations to match your specific settings and requirements.

```bash
cd deer-flow
cp conf.yaml.example conf.yaml
```

## Which models does DeerFlow support?

In DeerFlow, currently we only support non-reasoning models, which means models like OpenAI's o1/o3 or DeepSeek's R1 are not supported yet, but we will add support for them in the future.

### Supported Models

`doubao-1.5-pro-32k-250115`, `gpt-4o`, `qwen-max-latest`, `gemini-2.0-flash`, `deepseek-v3`, and theoretically any other non-reasoning chat models that implement the OpenAI API specification.

> [!NOTE]
> The Deep Research process requires the model to have a **longer context window**, which is not supported by all models.
> A work-around is to set the `Max steps of a research plan` to `2` in the settings dialog located on the top right corner of the web page,
> or set `max_step_num` to `2` when invoking the API.

### How to switch models?
You can switch the model in use by modifying the `conf.yaml` file in the root directory of the project, using the configuration in the [litellm format](https://docs.litellm.ai/docs/providers/openai_compatible).

---

### How to use OpenAI-Compatible models?

DeerFlow supports integration with OpenAI-Compatible models, which are models that implement the OpenAI API specification. This includes various open-source and commercial models that provide API endpoints compatible with the OpenAI format. You can refer to [litellm OpenAI-Compatible](https://docs.litellm.ai/docs/providers/openai_compatible) for detailed documentation.
The following is a configuration example of `conf.yaml` for using OpenAI-Compatible models:

```yaml
# An example of Doubao models served by VolcEngine
BASIC_MODEL:
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  model: "doubao-1.5-pro-32k-250115"
  api_key: YOUR_API_KEY

# An example of Aliyun models
BASIC_MODEL:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen-max-latest"
  api_key: YOUR_API_KEY

# An example of deepseek official models
BASIC_MODEL:
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  api_key: YOU_API_KEY

# An example of Google Gemini models using OpenAI-Compatible interface
BASIC_MODEL:
  base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
  model: "gemini-2.0-flash"
  api_key: YOUR_API_KEY
```

### How to use Ollama models?

DeerFlow supports the integration of Ollama models. You can refer to [litellm Ollama](https://docs.litellm.ai/docs/providers/ollama). <br>
The following is a configuration example of `conf.yaml` for using Ollama models:

```yaml
BASIC_MODEL:
  model: "ollama/ollama-model-name"
  base_url: "http://localhost:11434" # Local service address of Ollama, which can be started/viewed via ollama serve
```

### How to use OpenRouter models?

DeerFlow supports the integration of OpenRouter models. You can refer to [litellm OpenRouter](https://docs.litellm.ai/docs/providers/openrouter). To use OpenRouter models, you need to:
1. Obtain the OPENROUTER_API_KEY from OpenRouter (https://openrouter.ai/) and set it in the environment variable.
2. Add the `openrouter/` prefix before the model name.
3. Configure the correct OpenRouter base URL.

The following is a configuration example for using OpenRouter models:
1. Configure OPENROUTER_API_KEY in the environment variable (such as the `.env` file)
```ini
OPENROUTER_API_KEY=""
```
2. Set the model name in `conf.yaml`
```yaml
BASIC_MODEL:
  model: "openrouter/google/palm-2-chat-bison"
```

Note: The available models and their exact names may change over time. Please verify the currently available models and their correct identifiers in [OpenRouter's official documentation](https://openrouter.ai/docs).

### How to use Azure models?

DeerFlow supports the integration of Azure models. You can refer to [litellm Azure](https://docs.litellm.ai/docs/providers/azure). Configuration example of `conf.yaml`:
```yaml
BASIC_MODEL:
  model: "azure/gpt-4o-2024-08-06"
  api_base: $AZURE_API_BASE
  api_version: $AZURE_API_VERSION
  api_key: $AZURE_API_KEY
```

## Storage Configuration

DeerFlow allows you to configure different storage backends for the LangGraph workflow checkpoints. This enables persistence of workflow states across application restarts or even across different instances.

### Available Storage Options

1. **Memory Storage (Default)**
   - In-memory storage with no persistence across restarts
   - No additional dependencies required
   - Best for development and testing

2. **SQLite Storage**
   - Simple file-based persistence
   - Requires the `langgraph-checkpoint-sqlite` package
   - Good for single-instance deployments or light workloads

3. **PostgreSQL Storage**
   - Robust, scalable database persistence
   - Requires the `langgraph-checkpoint-postgres` package and a PostgreSQL server
   - Best for production environments and multi-instance deployments

### Configuration Examples

Add the following section to your `conf.yaml` file to configure the storage:

```yaml
# Memory Storage (Default)
STORAGE:
  type: memory

# SQLite Storage
STORAGE:
  type: sqlite
  db_path: checkpoints.sqlite  # Path to SQLite database file

# PostgreSQL Storage
STORAGE:
  type: postgres
  db_uri: postgres://username:password@localhost:5432/dbname  # PostgreSQL connection URI
```

### Installing Dependencies

To use SQLite or PostgreSQL storage, install the necessary dependencies:

```bash
# For SQLite storage
uv pip install langgraph-checkpoint-sqlite

# For PostgreSQL storage
uv pip install langgraph-checkpoint-postgres psycopg psycopg-pool
```

### Notes on Storage Selection

- Memory storage is fast but not persistent - all data will be lost when the application restarts
- SQLite is good for single-instance deployments with moderate persistence needs
- PostgreSQL is recommended for production deployments, especially when running multiple instances
- The system will fall back to memory storage if the configured storage type is not available or properly configured
