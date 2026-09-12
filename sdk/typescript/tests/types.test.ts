import { describe, expect, it } from "vitest";

import { DeerFlowClient } from "../src/client.js";
import type {
  DeerFlowClientOptions,
  MessageChunk,
  MessagesTupleEvent,
  StreamEvent,
  ThreadInfo,
  ValuesEvent,
} from "../src/types.js";

describe("types", () => {
  it("exposes expected client and type shapes", () => {
    const options: DeerFlowClientOptions = {
      baseUrl: "http://localhost:2026/api/langgraph",
    };

    const thread: ThreadInfo = {
      thread_id: "t-1",
      created_at: new Date().toISOString(),
      metadata: {},
    };

    const valuesEvent: ValuesEvent = {
      messages: [{ type: "ai", content: "hello" }],
      title: "Thread",
      artifacts: [],
    };

    const tupleEvent: MessagesTupleEvent = [{ id: "m1", type: "ai", content: "hel" }, {}];

    const streamEvent: StreamEvent = {
      event: "messages-tuple",
      data: tupleEvent,
    };

    const client = new DeerFlowClient(options);

    expect(client).toBeInstanceOf(DeerFlowClient);
    expect(thread.thread_id).toBe("t-1");
    expect(valuesEvent.messages.length).toBe(1);
    expect(streamEvent.event).toBe("messages-tuple");
  });

  it("StreamEvent union covers every SSE event the gateway can emit", () => {
    const messagesChunk: MessageChunk = { id: "m1", type: "ai", content: "hi" };

    const events: StreamEvent[] = [
      { event: "values", data: { messages: [] } },
      { event: "messages", data: messagesChunk },
      { event: "messages-tuple", data: [messagesChunk, {}] },
      { event: "custom", data: { foo: "bar" } },
      { event: "metadata", data: { run_id: "r1" } },
      { event: "error", data: { message: "boom" } },
      { event: "end", data: null },
    ];

    expect(events).toHaveLength(7);
    // Narrow each branch so the discriminated union is exercised at compile time.
    for (const evt of events) {
      switch (evt.event) {
        case "values":
          expect(Array.isArray(evt.data.messages)).toBe(true);
          break;
        case "messages":
          expect(evt.data.type).toBe("ai");
          break;
        case "messages-tuple":
          expect(evt.data[0]?.content).toBe("hi");
          break;
        case "custom":
          expect(typeof evt.data).toBe("object");
          break;
        case "metadata":
          expect(evt.data.run_id).toBe("r1");
          break;
        case "error":
          expect(evt.data.message).toBe("boom");
          break;
        case "end":
          expect(evt.data).toBeNull();
          break;
      }
    }
  });
});
