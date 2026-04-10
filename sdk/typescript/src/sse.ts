export type RawSSEEvent = {
  event: string;
  data: string;
};

export async function* parseSSEStream(body: ReadableStream<Uint8Array>): AsyncGenerator<RawSSEEvent> {
  const utf8Decoder = new TextDecoder();
  const decodedStream =
    typeof TextDecoderStream !== "undefined"
      ? body.pipeThrough(new TextDecoderStream() as unknown as TransformStream<Uint8Array, string>)
      : body.pipeThrough(
          new TransformStream<Uint8Array, string>({
            transform(chunk, controller) {
              controller.enqueue(utf8Decoder.decode(chunk, { stream: true }));
            },
          }),
        );

  const reader = decodedStream.getReader();
  let pending = "";
  let currentEvent = "message";
  let dataLines: string[] = [];

  const flush = async () => {
    if (dataLines.length === 0) {
      currentEvent = "message";
      return;
    }

    const data = dataLines.join("\n");
    dataLines = [];

    const event: RawSSEEvent = { event: currentEvent, data };
    currentEvent = "message";
    return event;
  };

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      if (pending.length > 0) {
        pending += "\n";
      }
      const tail = await flushPending(pending);
      pending = tail.pending;
      if (tail.events.length > 0) {
        for (const evt of tail.events) {
          if (evt.event !== "message" || evt.data !== "") {
            yield evt;
          }
        }
      }
      const evt = await flush();
      if (evt) {
        yield evt;
      }
      break;
    }

    pending += value;
    const result = await flushPending(pending);
    pending = result.pending;
    for (const evt of result.events) {
      if (evt.event !== "message" || evt.data !== "") {
        yield evt;
      }
    }
  }

  async function flushPending(input: string): Promise<{ pending: string; events: RawSSEEvent[] }> {
    const normalized = input.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = normalized.split("\n");
    const remainder = lines.pop() ?? "";
    const events: RawSSEEvent[] = [];

    for (const line of lines) {
      if (line === "") {
        const evt = await flush();
        if (evt) {
          events.push(evt);
        }
        continue;
      }

      if (line.startsWith(":")) {
        continue;
      }

      const colonIndex = line.indexOf(":");
      const field = colonIndex === -1 ? line : line.slice(0, colonIndex);
      let rawValue = colonIndex === -1 ? "" : line.slice(colonIndex + 1);
      if (rawValue.startsWith(" ")) {
        rawValue = rawValue.slice(1);
      }

      if (field === "event") {
        currentEvent = rawValue || "message";
      } else if (field === "data") {
        dataLines.push(rawValue);
      }
    }

    return { pending: remainder, events };
  }
}
