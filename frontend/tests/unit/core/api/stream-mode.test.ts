import { expect, test } from "@rstest/core";

import {
  CHAT_RUN_STREAM_MODES,
  forceChatRunStreamOptions,
  sanitizeRunStreamOptions,
} from "@/core/api/stream-mode";

test("rejects mixed supported and unsupported stream modes", () => {
  expect(() =>
    sanitizeRunStreamOptions({
      streamMode: ["values", "events", "tools"],
    }),
  ).toThrow("Unsupported LangGraph stream mode(s): events, tools");
});

test("rejects payloads when every requested stream mode is unsupported", () => {
  expect(() =>
    sanitizeRunStreamOptions({
      streamMode: ["events", "tools"],
    }),
  ).toThrow("Unsupported LangGraph stream mode(s): events, tools");

  expect(() =>
    sanitizeRunStreamOptions({
      streamMode: "tools",
    }),
  ).toThrow("Unsupported LangGraph stream mode(s): tools");
});

test("rejects messages because the Gateway only supports messages-tuple framing", () => {
  expect(() =>
    sanitizeRunStreamOptions({
      streamMode: "messages",
    }),
  ).toThrow("Unsupported LangGraph stream mode(s): messages");
});

test("keeps payloads without streamMode untouched", () => {
  const options = {
    streamSubgraphs: true,
  };

  expect(sanitizeRunStreamOptions(options)).toBe(options);
});

test("strips streamResumable before sending run options to the API", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamResumable: true,
    streamSubgraphs: true,
  });

  expect(sanitized).toEqual({
    streamSubgraphs: true,
  });
});

test("sanitizes streamResumable while preserving valid stream modes", () => {
  const sanitized = sanitizeRunStreamOptions({
    streamResumable: true,
    streamMode: ["values", "custom"],
  });

  expect(sanitized).toEqual({
    streamMode: ["values", "custom"],
  });
});

test("forces incremental modes for chat streams instead of values snapshots", () => {
  const sanitized = forceChatRunStreamOptions({
    streamResumable: true,
    streamMode: ["values", "messages-tuple", "updates", "custom", "debug"],
    signal: "keep-me",
  });

  expect(sanitized).toEqual({
    signal: "keep-me",
    streamMode: [...CHAT_RUN_STREAM_MODES, "debug"],
  });
  expect(sanitized.streamMode).not.toContain("values");
});

test("adds explicit chat stream modes when no options are provided", () => {
  expect(forceChatRunStreamOptions(undefined)).toEqual({
    streamMode: [...CHAT_RUN_STREAM_MODES],
  });
});

test("preserves a direct AbortSignal while adding chat stream modes", () => {
  const signal = new AbortController().signal;

  expect(forceChatRunStreamOptions(signal)).toEqual({
    signal,
    streamMode: [...CHAT_RUN_STREAM_MODES],
  });
});

test("rejects unsupported chat stream modes before replacing them", () => {
  expect(() =>
    forceChatRunStreamOptions({
      streamMode: ["messages-tuple", "events"],
    }),
  ).toThrow("Unsupported LangGraph stream mode(s): events");
});
