# @deerflow/client

Lightweight TypeScript client for DeerFlow's LangGraph HTTP API (`/api/langgraph`).

## Installation

```bash
npm install @deerflow/client
```

## Basic Usage

```ts
import { DeerFlowClient } from "@deerflow/client";

const client = new DeerFlowClient({
  baseUrl: "http://localhost:2026/api/langgraph",
});

const reply = await client.chat("What can you do?");
console.log(reply);
```

## Streaming Usage

```ts
import { DeerFlowClient } from "@deerflow/client";

const client = new DeerFlowClient({
  baseUrl: "http://localhost:2026/api/langgraph",
});

for await (const event of client.stream("Summarize the latest roadmap updates")) {
  if (event.event === "messages-tuple") {
    const [message] = event.data as [{ type?: string; content?: string }, Record<string, unknown>];
    if (message.type === "ai" && message.content) {
      process.stdout.write(message.content);
    }
  }

  if (event.event === "end") {
    process.stdout.write("\n");
  }
}
```

## Thread Management

```ts
import { DeerFlowClient } from "@deerflow/client";

const client = new DeerFlowClient({
  baseUrl: "http://localhost:2026/api/langgraph",
});

const thread = await client.createThread({ source: "sdk-example" });
console.log(thread.thread_id);

const state = await client.getThreadState(thread.thread_id);
console.log(state.messages.length);

const answer = await client.chat("Continue this thread", thread.thread_id);
console.log(answer);
```

## API

- `createThread(metadata?)` → creates a new thread
- `getThreadState(threadId)` → fetches latest thread state
- `stream(message, threadId?)` → async generator of SSE stream events
- `chat(message, threadId?)` → convenience method returning final AI text
