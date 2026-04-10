import { describe, expect, it } from "vitest";

import { DeerFlowClient } from "../src/client.js";
import type {
  DeerFlowClientOptions,
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
});
