import { describe, expect, it } from "vitest";

import { parseSSEStream } from "../src/sse.js";

function toStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("parseSSEStream", () => {
  it("parses basic events", async () => {
    const body = toStream([
      "event: values\n",
      "data: {\"messages\":[]}\n\n",
      "event: end\n",
      "data: {}\n\n",
    ]);

    const events: Array<{ event: string; data: string }> = [];
    for await (const evt of parseSSEStream(body)) {
      events.push(evt);
    }

    expect(events).toEqual([
      { event: "values", data: '{"messages":[]}' },
      { event: "end", data: "{}" },
    ]);
  });

  it("supports multiline data and chunk boundaries", async () => {
    const body = toStream([
      "event: custom\n",
      "data: line1\n",
      "data: line",
      "2\n\n",
    ]);

    const events: Array<{ event: string; data: string }> = [];
    for await (const evt of parseSSEStream(body)) {
      events.push(evt);
    }

    expect(events).toEqual([{ event: "custom", data: "line1\nline2" }]);
  });

  it("ignores comments and events without data", async () => {
    const body = toStream([": keepalive\n\n", "event: values\n", "data: {}\n\n"]);

    const events: Array<{ event: string; data: string }> = [];
    for await (const evt of parseSSEStream(body)) {
      events.push(evt);
    }

    expect(events).toEqual([{ event: "values", data: "{}" }]);
  });
});
