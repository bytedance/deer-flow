import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  buildThreadFileHistory,
  getThreadFileHistorySnapshots,
} from "@/core/artifacts/history";

test("buildThreadFileHistory reconstructs write_file and str_replace snapshots", () => {
  const messages = [
    {
      type: "ai",
      id: "message-1",
      content: "",
      tool_calls: [
        {
          id: "tool-1",
          name: "write_file",
          args: {
            description: "Create app entry",
            path: "/mnt/user-data/workspace/app/index.html",
            content: "<h1>Hello world</h1>",
          },
          type: "tool_call",
        },
      ],
      invalid_tool_calls: [],
    },
    {
      type: "tool",
      id: "result-1",
      name: "write_file",
      content: "OK",
      tool_call_id: "tool-1",
    },
    {
      type: "ai",
      id: "message-2",
      content: "",
      tool_calls: [
        {
          id: "tool-2",
          name: "str_replace",
          args: {
            description: "Update hero copy",
            path: "/mnt/user-data/workspace/app/index.html",
            old_str: "world",
            new_str: "DeerFlow",
          },
          type: "tool_call",
        },
      ],
      invalid_tool_calls: [],
    },
    {
      type: "tool",
      id: "result-2",
      name: "str_replace",
      content: "OK",
      tool_call_id: "tool-2",
    },
  ] as Message[];

  const history = buildThreadFileHistory(messages);

  expect(history["workspace/app/index.html"]).toEqual([
    {
      id: "tool-1",
      filepath: "/mnt/user-data/workspace/app/index.html",
      normalizedPath: "workspace/app/index.html",
      version: 1,
      sequence: 1,
      operation: "write_file",
      description: "Create app entry",
      content: "<h1>Hello world</h1>",
      previousContent: undefined,
      messageId: "message-1",
      toolCallId: "tool-1",
    },
    {
      id: "tool-2",
      filepath: "/mnt/user-data/workspace/app/index.html",
      normalizedPath: "workspace/app/index.html",
      version: 2,
      sequence: 2,
      operation: "str_replace",
      description: "Update hero copy",
      content: "<h1>Hello DeerFlow</h1>",
      previousContent: "<h1>Hello world</h1>",
      messageId: "message-2",
      toolCallId: "tool-2",
    },
  ]);

  expect(
    getThreadFileHistorySnapshots(
      messages,
      "/mnt/user-data/outputs/app/index.html",
    ),
  ).toEqual(history["workspace/app/index.html"]);
});

test("buildThreadFileHistory skips failed or non-reconstructable edits", () => {
  const messages = [
    {
      type: "ai",
      id: "message-1",
      content: "",
      tool_calls: [
        {
          id: "tool-1",
          name: "str_replace",
          args: {
            description: "Edit without a base snapshot",
            path: "/mnt/user-data/workspace/app/index.html",
            old_str: "Hello",
            new_str: "Hi",
          },
          type: "tool_call",
        },
      ],
      invalid_tool_calls: [],
    },
    {
      type: "tool",
      id: "result-1",
      name: "str_replace",
      content: "OK",
      tool_call_id: "tool-1",
    },
    {
      type: "ai",
      id: "message-2",
      content: "",
      tool_calls: [
        {
          id: "tool-2",
          name: "write_file",
          args: {
            description: "Create app entry",
            path: "/mnt/user-data/workspace/app/index.html",
            content: "<h1>Hello world</h1>",
          },
          type: "tool_call",
        },
      ],
      invalid_tool_calls: [],
    },
    {
      type: "tool",
      id: "result-2",
      name: "write_file",
      content: "OK",
      tool_call_id: "tool-2",
    },
    {
      type: "ai",
      id: "message-3",
      content: "",
      tool_calls: [
        {
          id: "tool-3",
          name: "str_replace",
          args: {
            description: "Apply a failing edit",
            path: "/mnt/user-data/workspace/app/index.html",
            old_str: "world",
            new_str: "team",
          },
          type: "tool_call",
        },
      ],
      invalid_tool_calls: [],
    },
    {
      type: "tool",
      id: "result-3",
      name: "str_replace",
      content: "Error: String to replace not found in file",
      tool_call_id: "tool-3",
    },
  ] as Message[];

  expect(getThreadFileHistorySnapshots(messages, "/mnt/user-data/outputs/app/index.html")).toEqual([
    {
      id: "tool-2",
      filepath: "/mnt/user-data/workspace/app/index.html",
      normalizedPath: "workspace/app/index.html",
      version: 1,
      sequence: 1,
      operation: "write_file",
      description: "Create app entry",
      content: "<h1>Hello world</h1>",
      previousContent: undefined,
      messageId: "message-2",
      toolCallId: "tool-2",
    },
  ]);
});
