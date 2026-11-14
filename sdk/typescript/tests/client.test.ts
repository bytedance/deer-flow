import { afterEach, describe, expect, it, vi } from "vitest";

import { DeerFlowClient } from "../src/client.js";

function sseResponse(frames: string[]): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder();
        for (const frame of frames) {
          controller.enqueue(encoder.encode(frame));
        }
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

describe("DeerFlowClient.chat", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads [chunk, metadata] tuples the gateway sends under the messages event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: messages\ndata: [{"id":"ai-1","type":"ai","content":"Hel"},{"langgraph_node":"agent"}]\n\n',
          'event: messages\ndata: [{"id":"ai-1","type":"ai","content":"lo"},{"langgraph_node":"agent"}]\n\n',
          "event: end\ndata: {}\n\n",
        ]),
      ),
    );

    const client = new DeerFlowClient({ baseUrl: "http://localhost:2026/api/langgraph" });

    await expect(client.chat("hi", "t-1")).resolves.toBe("Hello");
  });

  it("still accepts bare chunks and messages-tuple events", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: messages\ndata: {"id":"ai-1","type":"ai","content":"a"}\n\n',
          'event: messages-tuple\ndata: [{"id":"ai-1","type":"ai","content":"b"},{}]\n\n',
          "event: end\ndata: {}\n\n",
        ]),
      ),
    );

    const client = new DeerFlowClient({ baseUrl: "http://localhost:2026/api/langgraph" });

    await expect(client.chat("hi", "t-1")).resolves.toBe("ab");
  });
});
