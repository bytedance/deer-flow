# Configuration Guide

## Quick Settings

Copy the `conf.yaml.example` file to `conf.yaml` and modify the configurations to match your specific settings and requirements.

```bash
cd deer-flow
cp conf.yaml.example conf.yaml
```

## Which models does DeerFlow support?

In DeerFlow, we currently only support non-reasoning models. This means models like OpenAI's o1/o3 or DeepSeek's R1 are not supported yet, but we plan to add support for them in the future. Additionally, all Gemma-3 models are currently unsupported due to the lack of tool usage capabilities.

### Supported Models

`doubao-1.5-pro-32k-250115`, `gpt-4o`, `qwen-max-latest`,`qwen3-235b-a22b`,`qwen3-coder`, `gemini-2.0-flash`, `deepseek-v3`, and theoretically any other non-reasoning chat models that implement the OpenAI API specification.

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
  api_key: YOUR_API_KEY

# An example of Google Gemini models using OpenAI-Compatible interface
BASIC_MODEL:
  base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
  model: "gemini-2.0-flash"
  api_key: YOUR_API_KEY
```
The following is a configuration example of `conf.yaml` for using best opensource OpenAI-Compatible models:
```yaml
# Use latest deepseek-v3 to handle basic tasks, the open source SOTA model for basic tasks
BASIC_MODEL:
  base_url: https://api.deepseek.com
  model: "deepseek-v3"
  api_key: YOUR_API_KEY
  temperature: 0.6
  top_p: 0.90
# Use qwen3-235b-a22b to handle reasoning tasks, the open source SOTA model for reasoning
REASONING_MODEL:
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  model: "qwen3-235b-a22b-thinking-2507"
  api_key: YOUR_API_KEY
  temperature: 0.6
  top_p: 0.90
# Use qwen3-coder-480b-a35b-instruct to handle coding tasks, the open source SOTA model for coding
CODE_MODEL:
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  model: "qwen3-coder-480b-a35b-instruct"
  api_key: YOUR_API_KEY
  temperature: 0.6
  top_p: 0.90
```
In addition, you need to set the `AGENT_LLM_MAP` in `src/config/agents.py` to use the correct model for each agent. For example:

```python
# Define agent-LLM mapping
AGENT_LLM_MAP: dict[str, LLMType] = {
    "coordinator": "reasoning",
    "planner": "reasoning",
    "researcher": "reasoning",
    "coder": "basic",
    "reporter": "basic",
    "podcast_script_writer": "basic",
    "ppt_composer": "basic",
    "prose_writer": "basic",
    "prompt_enhancer": "basic",
}

```
### How to use models with self-signed SSL certificates?

If your LLM server uses self-signed SSL certificates, you can disable SSL certificate verification by adding the `verify_ssl: false` parameter to your model configuration:

```yaml
BASIC_MODEL:
  base_url: "https://your-llm-server.com/api/v1"
  model: "your-model-name"
  api_key: YOUR_API_KEY
  verify_ssl: false  # Disable SSL certificate verification for self-signed certificates
```

> [!WARNING]
> Disabling SSL certificate verification reduces security and should only be used in development environments or when you trust the LLM server. In production environments, it's recommended to use properly signed SSL certificates.

### How to use Ollama models?

DeerFlow supports the integration of Ollama models. You can refer to [litellm Ollama](https://docs.litellm.ai/docs/providers/ollama). <br>
The following is a configuration example of `conf.yaml` for using Ollama models(you might need to run the 'ollama serve' first):

```yaml
BASIC_MODEL:
  model: "model-name"  # Model name, which supports the completions API(important), such as: qwen3:8b, mistral-small3.1:24b, qwen2.5:3b
  base_url: "http://localhost:11434/v1" # Local service address of Ollama, which can be started/viewed via ollama serve
  api_key: "whatever"  # Mandatory, fake api_key with a random string you like :-)
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


### How to use Azure OpenAI chat models?

DeerFlow supports the integration of Azure OpenAI chat models. You can refer to [AzureChatOpenAI](https://python.langchain.com/api_reference/openai/chat_models/langchain_openai.chat_models.azure.AzureChatOpenAI.html). Configuration example of `conf.yaml`:
```yaml
BASIC_MODEL:
  model: "azure/gpt-4o-2024-08-06"
  azure_endpoint: $AZURE_OPENAI_ENDPOINT
  api_version: $OPENAI_API_VERSION
  api_key: $AZURE_OPENAI_API_KEY
```

## About Search Engine

### How to control search domains for Tavily?

DeerFlow allows you to control which domains are included or excluded in Tavily search results through the configuration file. This helps improve search result quality and reduce hallucinations by focusing on trusted sources.

`Tips`: it only supports Tavily currently. 

You can configure domain filtering in your `conf.yaml` file as follows:

```yaml
SEARCH_ENGINE:
  engine: tavily
  # Only include results from these domains (whitelist)
  include_domains:
    - trusted-news.com
    - gov.org
    - reliable-source.edu
  # Exclude results from these domains (blacklist)
  exclude_domains:
    - unreliable-site.com
    - spam-domain.net

