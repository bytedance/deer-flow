import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import { enUS } from "@/core/i18n";
import {
  buildTokenDebugSteps,
  getTokenUsageViewPreset,
  tokenUsagePreferencesFromPreset,
} from "@/core/messages/usage-model";

test("maps token usage presets to persisted preferences", () => {
  expect(tokenUsagePreferencesFromPreset("off")).toEqual({
    headerTotal: false,
    inlineMode: "off",
  });
  expect(tokenUsagePreferencesFromPreset("summary")).toEqual({
    headerTotal: true,
    inlineMode: "off",
  });
  expect(tokenUsagePreferencesFromPreset("per_turn")).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
  expect(tokenUsagePreferencesFromPreset("debug")).toEqual({
    headerTotal: true,
    inlineMode: "step_debug",
  });
});

test("derives the active preset from persisted preferences", () => {
  expect(
    getTokenUsageViewPreset({
      headerTotal: false,
      inlineMode: "off",
    }),
  ).toBe("off");

  expect(
    getTokenUsageViewPreset({
      headerTotal: true,
      inlineMode: "off",
    }),
  ).toBe("summary");

  expect(
    getTokenUsageViewPreset({
      headerTotal: true,
      inlineMode: "per_turn",
    }),
  ).toBe("per_turn");

  expect(
    getTokenUsageViewPreset({
      headerTotal: true,
      inlineMode: "step_debug",
    }),
  ).toBe("debug");
});

test("builds todo-aware debug step labels across the full thread", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "write_todos:1",
          name: "write_todos",
          args: {
            todos: [{ content: "Draft the plan", status: "in_progress" }],
          },
        },
      ],
      usage_metadata: {
        input_tokens: 100,
        output_tokens: 20,
        total_tokens: 120,
      },
    },
    {
      id: "tool-1",
      type: "tool",
      name: "write_todos",
      tool_call_id: "write_todos:1",
      content: "ok",
    },
    {
      id: "ai-2",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "write_todos:2",
          name: "write_todos",
          args: {
            todos: [{ content: "Draft the plan", status: "completed" }],
          },
        },
      ],
      usage_metadata: { input_tokens: 50, output_tokens: 10, total_tokens: 60 },
    },
    {
      id: "ai-3",
      type: "ai",
      content: "Here is the result",
      usage_metadata: { input_tokens: 40, output_tokens: 15, total_tokens: 55 },
    },
  ] as Message[];

  expect(buildTokenDebugSteps(messages, enUS)).toEqual([
    expect.objectContaining({
      messageId: "ai-1",
      label: "Start To-do: Draft the plan",
      sharedAttribution: false,
    }),
    expect.objectContaining({
      messageId: "ai-2",
      label: "Complete To-do: Draft the plan",
      sharedAttribution: false,
    }),
    expect.objectContaining({
      messageId: "ai-3",
      label: "Final answer",
      sharedAttribution: false,
    }),
  ]);
});

test("marks multi-action AI steps as shared attribution", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "web_search:1",
          name: "web_search",
          args: { query: "LangGraph stream mode" },
        },
        {
          id: "write_todos:1",
          name: "write_todos",
          args: {
            todos: [
              {
                content: "Inspect stream mode handling",
                status: "in_progress",
              },
            ],
          },
        },
      ],
      usage_metadata: {
        input_tokens: 120,
        output_tokens: 30,
        total_tokens: 150,
      },
    },
  ] as Message[];

  expect(buildTokenDebugSteps(messages, enUS)).toEqual([
    expect.objectContaining({
      messageId: "ai-1",
      label: "Step total",
      sharedAttribution: true,
      secondaryLabels: [
        'Search for "LangGraph stream mode"',
        "Start To-do: Inspect stream mode handling",
      ],
    }),
  ]);
});

test("prefers backend attribution metadata when available", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "write_todos:1",
          name: "write_todos",
          args: {
            todos: [
              {
                content: "Fallback label should not win",
                status: "in_progress",
              },
            ],
          },
        },
      ],
      additional_kwargs: {
        token_usage_attribution: {
          version: 1,
          kind: "todo_update",
          shared_attribution: false,
          actions: [{ kind: "todo_start", content: "Use backend attribution" }],
        },
      },
      usage_metadata: { input_tokens: 25, output_tokens: 5, total_tokens: 30 },
    },
  ] as Message[];

  expect(buildTokenDebugSteps(messages, enUS)).toEqual([
    expect.objectContaining({
      messageId: "ai-1",
      label: "Start To-do: Use backend attribution",
      sharedAttribution: false,
    }),
  ]);
});

test("falls back safely when attribution payload is malformed", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "web_search:1",
          name: "web_search",
          args: { query: "LangGraph stream mode" },
        },
      ],
      additional_kwargs: {
        token_usage_attribution: {
          version: 1,
          kind: "tool_batch",
          actions: { broken: true },
        },
      },
      usage_metadata: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
    },
  ] as Message[];

  expect(buildTokenDebugSteps(messages, enUS)).toEqual([
    expect.objectContaining({
      messageId: "ai-1",
      label: 'Search for "LangGraph stream mode"',
      sharedAttribution: false,
    }),
  ]);
});

test("labels removal-only todo updates even when backend attribution has no actions", () => {
  const messages = [
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "write_todos:1",
          name: "write_todos",
          args: {
            todos: [{ content: "Clean up stale tasks", status: "in_progress" }],
          },
        },
      ],
      usage_metadata: {
        input_tokens: 100,
        output_tokens: 20,
        total_tokens: 120,
      },
    },
    {
      id: "ai-2",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "write_todos:2",
          name: "write_todos",
          args: {
            todos: [],
          },
        },
      ],
      additional_kwargs: {
        token_usage_attribution: {
          version: 1,
          kind: "todo_update",
          shared_attribution: false,
          actions: [],
        },
      },
      usage_metadata: { input_tokens: 30, output_tokens: 8, total_tokens: 38 },
    },
  ] as Message[];

  expect(buildTokenDebugSteps(messages, enUS)).toEqual([
    expect.objectContaining({
      messageId: "ai-1",
      label: "Start To-do: Clean up stale tasks",
    }),
    expect.objectContaining({
      messageId: "ai-2",
      label: "Remove To-do: Clean up stale tasks",
      sharedAttribution: false,
    }),
  ]);
});
