// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { env } from "~/env";

import { type StreamEvent } from "./StreamEvent";

export async function* fetchStream(
  url: string,
  init: RequestInit,
): AsyncIterable<StreamEvent> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-cache",
    },
    ...init,
  });
  if (response.status !== 200) {
    throw new Error(`Failed to fetch from ${url}: ${response.status}`);
  }
  // Read from response body, event by event. An event always ends with a '\n\n'.
  const reader = response.body
    ?.pipeThrough(new TextDecoderStream())
    .getReader();
  if (!reader) {
    throw new Error("Response body is not readable");
  }

  try {
    let buffer = "";
    // Use configurable buffer size from environment, default to 1MB (1048576 bytes)
    const MAX_BUFFER_SIZE = env.NEXT_PUBLIC_MAX_STREAM_BUFFER_SIZE ?? (1024 * 1024);

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        // Handle remaining buffer data
        if (buffer.trim()) {
          const event = parseEvent(buffer.trim());
          if (event) {
            yield event;
          }
        }
        break;
      }

      buffer += value;

      // Check buffer size to avoid memory overflow
      if (buffer.length > MAX_BUFFER_SIZE) {
        throw new Error(
          `Buffer overflow - received ${Math.round(buffer.length / 1024 / 1024)}MB of data without proper event boundaries. ` +
          `Max buffer size is ${Math.round(MAX_BUFFER_SIZE / 1024 / 1024)}MB. ` +
          `You can increase this by setting NEXT_PUBLIC_MAX_STREAM_BUFFER_SIZE environment variable.`
        );
      }

      let newlineIndex;
      while ((newlineIndex = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 2);

        if (chunk.trim()) {
          const event = parseEvent(chunk);
          if (event) {
            yield event;
          }
        }
      }
    }
  } finally {
    reader.releaseLock(); // Release the reader lock
  }

}

function parseEvent(chunk: string) {
  let resultEvent = "message";
  let resultData: string | null = null;
  for (const line of chunk.split("\n")) {
    const pos = line.indexOf(": ");
    if (pos === -1) {
      continue;
    }
    const key = line.slice(0, pos);
    const value = line.slice(pos + 2);
    if (key === "event") {
      resultEvent = value;
    } else if (key === "data") {
      resultData = value;
    }
  }
  if (resultEvent === "message" && resultData === null) {
    return undefined;
  }
  return {
    event: resultEvent,
    data: resultData,
  } as StreamEvent;
}
