# DeerFlow API Documentation

## Overview

DeerFlow API is a comprehensive backend service for advanced research and content generation. It provides endpoints for chat-based research, text-to-speech conversion, content generation (podcasts, presentations, prose), prompt enhancement, and RAG (Retrieval-Augmented Generation) functionality.

**API Version:** 0.1.0  
**Base URL:** `http://localhost:8000`

---

## Authentication

Currently, the API does not require authentication. CORS is configured with origins defined by the `ALLOWED_ORIGINS` environment variable (default: `http://localhost:3000`).

---

## API Endpoints

### Chat & Research

#### `POST /api/chat/stream`

Initiates a streaming chat session with the research agent. Returns Server-Sent Events (SSE) with message chunks, tool calls, and intermediate results.

**Request Body:**
```json
{
  "messages": [
    {
      "role": "user",
      "content": "What is quantum computing?"
    }
  ],
  "thread_id": "__default__",
  "max_plan_iterations": 1,
  "max_step_num": 3,
  "max_search_results": 3,
  "auto_accepted_plan": false,
  "report_style": "ACADEMIC",
  "enable_background_investigation": true,
  "enable_deep_thinking": false,
  "enable_clarification": false
}
```

**Query Parameters:**
- `messages` (required, array[ChatMessage]): History of messages between user and assistant
- `resources` (optional, array[Resource]): Resources for the research
- `thread_id` (optional, string, default: `"__default__"`): Conversation identifier
- `max_plan_iterations` (optional, integer, default: 1): Maximum number of plan iterations
- `max_step_num` (optional, integer, default: 3): Maximum number of steps in a plan
- `max_search_results` (optional, integer, default: 3): Maximum number of search results
- `auto_accepted_plan` (optional, boolean, default: false): Automatically accept the plan
- `interrupt_feedback` (optional, string): User feedback on the plan
- `mcp_settings` (optional, object): MCP settings (requires `ENABLE_MCP_SERVER_CONFIGURATION=true`)
- `enable_background_investigation` (optional, boolean, default: true): Get background investigation before plan
- `report_style` (optional, enum): Style of the report - `ACADEMIC`, `POPULAR_SCIENCE`, `NEWS`, `SOCIAL_MEDIA`, `STRATEGIC_INVESTMENT`
- `enable_deep_thinking` (optional, boolean, default: false): Enable deep thinking
- `enable_clarification` (optional, boolean): Enable multi-turn clarification
- `max_clarification_rounds` (optional, integer): Maximum clarification rounds

**Response:**
- Content-Type: `text/event-stream`
- Server-sent events with various message types:
  - `message_chunk`: Raw message tokens
  - `tool_calls`: Tool invocations
  - `tool_call_chunks`: Partial tool call data
  - `tool_call_result`: Result of a tool call
  - `interrupt`: Plan interruption for user feedback
  - `error`: Error messages

**Example Response (Server-Sent Events):**
```
event: message_chunk
data: {"thread_id":"abc123","agent":"researcher","role":"assistant","content":"I'll search for information about quantum computing..."}

event: tool_calls
data: {"thread_id":"abc123","agent":"researcher","tool_calls":[{"name":"web_search","args":"{\"query\":\"quantum computing\"}"}]}

event: tool_call_result
data: {"thread_id":"abc123","agent":"researcher","content":"Found 10 results about quantum computing"}
```

**Error Responses:**
- `403`: MCP server configuration is disabled
- `500`: Internal server error during graph execution

---

### Text-to-Speech

#### `POST /api/tts`

Converts text to speech using Volcengine TTS API.

**Requirements:**
- Environment variables must be set:
  - `VOLCENGINE_TTS_APPID`
  - `VOLCENGINE_TTS_ACCESS_TOKEN`

**Request Body:**
```json
{
  "text": "Hello, this is a test",
  "encoding": "mp3",
  "voice_type": "BV700_V2_streaming",
  "speed_ratio": 1.0,
  "volume_ratio": 1.0,
  "pitch_ratio": 1.0,
  "text_type": "plain",
  "with_frontend": 1,
  "frontend_type": "unitTson"
}
```

**Parameters:**
- `text` (required, string, max 1024 chars): Text to convert to speech
- `encoding` (optional, string, default: `"mp3"`): Audio format - `mp3`, `wav`
- `voice_type` (optional, string, default: `"BV700_V2_streaming"`): Voice type
- `speed_ratio` (optional, float, default: 1.0): Speech speed ratio
- `volume_ratio` (optional, float, default: 1.0): Speech volume ratio
- `pitch_ratio` (optional, float, default: 1.0): Speech pitch ratio
- `text_type` (optional, string, default: `"plain"`): `plain` or `ssml`
- `with_frontend` (optional, integer, default: 1): Enable frontend processing
- `frontend_type` (optional, string, default: `"unitTson"`): Frontend type

**Response:**
- Content-Type: `audio/mp3` or `audio/wav` (depends on encoding)
- Binary audio data
- Header: `Content-Disposition: attachment; filename=tts_output.{encoding}`

**Error Responses:**
- `400`: Missing required environment variables
- `500`: Internal server error during TTS processing

---

### Content Generation

#### `POST /api/podcast/generate`

Generates an audio podcast from provided text content.

**Request Body:**
```json
{
  "content": "# Podcast Content\nThis is the content of the podcast..."
}
```

**Parameters:**
- `content` (required, string): Podcast content in text format

**Response:**
- Content-Type: `audio/mp3`
- Binary audio data

**Error Responses:**
- `500`: Error during podcast generation

---

#### `POST /api/ppt/generate`

Generates a PowerPoint presentation from provided content.

**Request Body:**
```json
{
  "content": "# Presentation Title\n## Slide 1\nContent here..."
}
```

**Parameters:**
- `content` (required, string): Content for the presentation

**Response:**
- Content-Type: `application/vnd.openxmlformats-officedocument.presentationml.presentation`
- Binary PowerPoint file (.pptx)
- Header: `Content-Disposition: attachment; filename=output.pptx`

**Error Responses:**
- `500`: Error during PPT generation

---

#### `POST /api/prose/generate`

Generates prose content with streaming output based on prompt and option.

**Request Body:**
```json
{
  "prompt": "Write a creative story about",
  "option": "story",
  "command": "make it exciting"
}
```

**Parameters:**
- `prompt` (required, string): Content/prompt for prose generation
- `option` (required, string): Prose writing option
- `command` (optional, string, default: `""`): User custom command

**Response:**
- Content-Type: `text/event-stream`
- Server-sent events with prose content chunks

**Example Response:**
```
data: "Once upon a time, there was..."

data: " a mysterious kingdom..."
```

**Error Responses:**
- `500`: Error during prose generation

---

### Prompt Enhancement

#### `POST /api/prompt/enhance`

Enhances and refines user prompts with specified report style and context.

**Request Body:**
```json
{
  "prompt": "Tell me about climate change",
  "context": "For a scientific audience",
  "report_style": "ACADEMIC"
}
```

**Parameters:**
- `prompt` (required, string): Original prompt to enhance
- `context` (optional, string, default: `""`): Additional context about intended use
- `report_style` (optional, string, default: `"academic"`): Style - `academic`, `popular_science`, `news`, `social_media`, `strategic_investment`

**Response:**
```json
{
  "result": "Enhanced and refined prompt here..."
}
```

**Error Responses:**
- `500`: Error during prompt enhancement

---

### MCP Integration

#### `POST /api/mcp/server/metadata`

Retrieves metadata and available tools from a Model Context Protocol (MCP) server.

**Requirements:**
- Environment variable: `ENABLE_MCP_SERVER_CONFIGURATION=true`

**Request Body - For stdio transport:**
```json
{
  "transport": "stdio",
  "command": "python",
  "args": ["-m", "mcp_server"],
  "env": {
    "VAR_NAME": "value"
  },
  "timeout_seconds": 300
}
```

**Request Body - For SSE transport:**
```json
{
  "transport": "sse",
  "url": "https://mcp-server.example.com",
  "headers": {
    "Authorization": "Bearer token"
  }
}
```

**Parameters:**
- `transport` (required, string): `stdio`, `sse`, or `streamable_http`
- `command` (optional, string): Command to execute (stdio type)
- `args` (optional, array[string]): Command arguments (stdio type)
- `url` (optional, string): Server URL (sse/streamable_http type)
- `env` (optional, object): Environment variables (stdio type)
- `headers` (optional, object): HTTP headers (sse/streamable_http type)
- `timeout_seconds` (optional, integer): Custom timeout in seconds (default: 300)

**Response:**
```json
{
  "transport": "stdio",
  "command": "python",
  "args": ["-m", "mcp_server"],
  "tools": [
    {
      "name": "tool_1",
      "description": "Description of tool",
      "parameters": {}
    }
  ]
}
```

**Error Responses:**
- `403`: MCP server configuration is disabled
- `500`: Error retrieving MCP server metadata

---

### RAG Configuration

#### `GET /api/rag/config`

Returns the current RAG (Retrieval-Augmented Generation) provider configuration.

**Response:**
```json
{
  "provider": "ragflow"
}
```

**Error Responses:**
- None (always returns 200)

---

#### `GET /api/rag/resources`

Retrieves available resources from the RAG system based on optional query.

**Query Parameters:**
- `query` (optional, string): Search query for resources

**Response:**
```json
{
  "resources": [
    {
      "id": "resource_1",
      "name": "Document",
      "type": "pdf"
    }
  ]
}
```

**Error Responses:**
- None (returns empty resources array if retriever not configured)

---

### Server Configuration

#### `GET /api/config`

Returns the complete server configuration including RAG settings and available models.

**Response:**
```json
{
  "rag": {
    "provider": "ragflow"
  },
  "models": {
    "llm": ["gpt-4", "gpt-3.5-turbo"],
    "embedding": ["openai-embedding"]
  }
}
```

**Error Responses:**
- None (always returns 200)

---

## Data Structures

### ChatMessage
```json
{
  "role": "user or assistant",
  "content": "string or array of ContentItem"
}
```

### ContentItem
```json
{
  "type": "text or image",
  "text": "string (for text type)",
  "image_url": "string (for image type)"
}
```

### ReportStyle Enum
- `ACADEMIC`
- `POPULAR_SCIENCE`
- `NEWS`
- `SOCIAL_MEDIA`
- `STRATEGIC_INVESTMENT`

---

## Error Handling

All endpoints follow standard HTTP status codes:

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Bad Request - Invalid parameters |
| 403 | Forbidden - Feature disabled or unauthorized |
| 500 | Internal Server Error |

Error response format:
```json
{
  "detail": "Error message describing what went wrong"
}
```

---

## Streaming Responses

Several endpoints return streaming responses using Server-Sent Events (SSE):

- `/api/chat/stream` - Chat streaming
- `/api/prose/generate` - Prose generation streaming

To consume SSE in your client:
```javascript
const eventSource = new EventSource('/api/chat/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({...})
});

eventSource.addEventListener('message_chunk', (event) => {
  console.log(event.data);
});
```

---

## Rate Limiting & Quotas

Currently no rate limiting is implemented. The system respects the following limits:
- TTS text input: max 1024 characters
- Search results: configurable via `max_search_results`
- Plan iterations: configurable via `max_plan_iterations`

---

## Environment Variables

Key environment variables for API configuration:

```bash
# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173

# TTS
VOLCENGINE_TTS_APPID=your_app_id
VOLCENGINE_TTS_ACCESS_TOKEN=your_access_token
VOLCENGINE_TTS_CLUSTER=volcano_tts
VOLCENGINE_TTS_VOICE_TYPE=BV700_V2_streaming

# MCP
ENABLE_MCP_SERVER_CONFIGURATION=false

# Checkpointing
LANGGRAPH_CHECKPOINT_SAVER=false
LANGGRAPH_CHECKPOINT_DB_URL=postgresql://user:pass@localhost/db

# RAG
RAG_PROVIDER=ragflow
```

---

## Examples

### Example 1: Chat with Research
```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What are the latest AI trends?"}],
    "thread_id": "conversation_1",
    "max_search_results": 5,
    "report_style": "POPULAR_SCIENCE"
  }'
```

### Example 2: Text-to-Speech
```bash
curl -X POST http://localhost:8000/api/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello world",
    "encoding": "mp3",
    "speed_ratio": 1.2
  }' \
  --output audio.mp3
```

### Example 3: Enhance Prompt
```bash
curl -X POST http://localhost:8000/api/prompt/enhance \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Tell me about space",
    "context": "For kids aged 8-10",
    "report_style": "POPULAR_SCIENCE"
  }'
```

### Example 4: Get Server Configuration
```bash
curl -X GET http://localhost:8000/api/config
```

---

## Changelog

### Version 0.1.0
- Initial API release
- Chat streaming with research capabilities
- Text-to-speech conversion
- Content generation (podcasts, presentations, prose)
- Prompt enhancement
- MCP server integration
- RAG configuration and resources

---

## Support

For issues or questions about the API, please refer to the project documentation or file an issue in the repository.
