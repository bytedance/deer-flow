import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import { buildThreadSubmitMessages } from "@/core/threads/hooks";

test("builds thread submit messages with hidden sidecar context before the visible user message", () => {
  const hiddenContext = {
    type: "human",
    content: "Hidden sidecar context",
    additional_kwargs: {
      hide_from_ui: true,
      sidecar_context: true,
    },
  } as Message;

  const messages = buildThreadSubmitMessages({
    text: "What should we do next?",
    additionalInputMessages: [hiddenContext],
  });

  expect(messages).toEqual([
    hiddenContext,
    {
      type: "human",
      content: [{ type: "text", text: "What should we do next?" }],
      additional_kwargs: {},
    },
  ]);
});

test("keeps uploaded files on the visible user message only", () => {
  const messages = buildThreadSubmitMessages({
    text: "Use this file",
    additionalInputMessages: [
      {
        type: "human",
        content: "Hidden sidecar context",
        additional_kwargs: { hide_from_ui: true },
      } as Message,
    ],
    filesForSubmit: [
      {
        filename: "report.pdf",
        size: 42,
        path: "/uploads/report.pdf",
        status: "uploaded",
      },
    ],
  });

  expect(messages[0]?.additional_kwargs).toEqual({ hide_from_ui: true });
  expect(messages[1]?.additional_kwargs).toEqual({
    files: [
      {
        filename: "report.pdf",
        size: 42,
        path: "/uploads/report.pdf",
        status: "uploaded",
      },
    ],
  });
});
