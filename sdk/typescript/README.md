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

The client requests `stream_mode: ["values", "messages-tuple", "custom"]` by default, matching the `useStream` contract the DeerFlow frontend relies on. `StreamEvent` is a discriminated union covering every SSE event the gateway can emit (`values`, `messages`, `messages-tuple`, `custom`, `metadata`, `error`, `end`), so handlers can branch safely on `event.event` without casting.

```ts
import { DeerFlowClient } from "@deerflow/client";

const client = new DeerFlowClient({
  baseUrl: "http://localhost:2026/api/langgraph",
});

for await (const event of client.stream("Summarize the latest roadmap updates")) {
  if (event.event === "messages-tuple") {
    const [message] = event.data;
    if (message.type === "ai" && typeof message.content === "string") {
      process.stdout.write(message.content);
    }
  } else if (event.event === "messages") {
    // Plain stream_mode=messages (no tuple wrapper)
    if (event.data.type === "ai" && typeof event.data.content === "string") {
      process.stdout.write(event.data.content);
    }
  } else if (event.event === "end") {
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
