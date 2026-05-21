import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import {
  formatThreadAsJSON,
  formatThreadAsMarkdown,
} from "@/core/threads/export";
import type { AgentThread } from "@/core/threads/types";

// Bytedance/deer-flow issue #3107 BUG-006: the chat export path bypasses the
// UI-level hidden-message filter and emits reasoning content, tool calls, and
// any other "internal" payload as if it were part of the user transcript.

function makeThread(): AgentThread {
  return {
    thread_id: "thread-1",
    created_at: "2026-05-21T00:00:00Z",
    updated_at: "2026-05-21T00:00:00Z",
    metadata: { title: "Demo thread" },
    status: "idle",
    values: { messages: [] },
  } as unknown as AgentThread;
}

function human(content: string, extra: Partial<Message> = {}): Message {
  return {
    id: `h-${content}`,
    type: "human",
    content,
    ...extra,
  } as Message;
}

function ai(
  content: string,
  extra: Partial<Message> & { tool_calls?: unknown } = {},
): Message {
  return {
    id: `a-${content}`,
    type: "ai",
    content,
    ...extra,
  } as Message;
}

function toolMsg(content: string): Message {
  return {
    id: `t-${content}`,
    type: "tool",
    content,
    name: "task",
    tool_call_id: "call-1",
  } as unknown as Message;
}

describe("formatThreadAsMarkdown", () => {
  it("includes plain user and assistant text", () => {
    const md = formatThreadAsMarkdown(makeThread(), [
      human("hello"),
      ai("hi there"),
    ]);
    expect(md).toContain("hello");
    expect(md).toContain("hi there");
  });

  it("drops messages marked hide_from_ui", () => {
    const hidden = human("internal system reminder", {
      additional_kwargs: { hide_from_ui: true },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [
      hidden,
      ai("public answer"),
    ]);
    expect(md).not.toContain("internal system reminder");
    expect(md).toContain("public answer");
  });

  it("does not emit reasoning_content by default", () => {
    const message = ai("final answer", {
      additional_kwargs: {
        reasoning_content: "secret chain of thought",
      },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message]);
    expect(md).not.toContain("secret chain of thought");
    expect(md).not.toContain("Thinking");
  });

  it("does not emit tool calls by default", () => {
    const message = ai("ok", {
      tool_calls: [{ id: "1", name: "task", args: { description: "do work" } }],
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message]);
    expect(md).not.toContain("**Tool:**");
    expect(md).not.toContain("`task`");
  });

  it("drops tool result messages", () => {
    const md = formatThreadAsMarkdown(makeThread(), [
      ai("delegating"),
      toolMsg("Task Succeeded. Result: confidential"),
    ]);
    expect(md).not.toContain("confidential");
  });
});

describe("formatThreadAsMarkdown opt-in flags", () => {
  it("emits reasoning when includeReasoning is true", () => {
    const message = ai("final answer", {
      additional_kwargs: {
        reasoning_content: "step-by-step chain of thought",
      },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message], {
      includeReasoning: true,
    });
    expect(md).toContain("step-by-step chain of thought");
    expect(md).toContain("Thinking");
  });

  it("emits tool call rows when includeToolCalls is true", () => {
    const message = ai("ok", {
      tool_calls: [{ id: "1", name: "task", args: { description: "do work" } }],
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [message], {
      includeToolCalls: true,
    });
    expect(md).toContain("**Tool:**");
    expect(md).toContain("`task`");
  });

  it("keeps hidden messages when includeHidden is true", () => {
    const hidden = human("internal reminder", {
      additional_kwargs: { hide_from_ui: true },
    } as Partial<Message>);
    const md = formatThreadAsMarkdown(makeThread(), [hidden], {
      includeHidden: true,
    });
    expect(md).toContain("internal reminder");
  });
});

describe("formatThreadAsJSON opt-in flags", () => {
  it("emits tool_calls field when includeToolCalls is true", () => {
    const message = ai("ok", {
      tool_calls: [{ id: "1", name: "task", args: { description: "x" } }],
    } as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message], {
      includeToolCalls: true,
    });
    expect(raw).toContain("tool_calls");
    expect(raw).toContain('"task"');
  });

  it("keeps tool messages when includeToolMessages is true", () => {
    const raw = formatThreadAsJSON(
      makeThread(),
      [toolMsg("Task Succeeded. Result: keep me")],
      { includeToolMessages: true },
    );
    const parsed = JSON.parse(raw) as { messages: { type: string }[] };
    expect(parsed.messages.some((m) => m.type === "tool")).toBe(true);
    expect(raw).toContain("keep me");
  });
});

describe("formatThreadAsJSON", () => {
  it("strips hidden messages, tool messages, reasoning, and tool calls", () => {
    const messages = [
      human("hello"),
      human("secret reminder", {
        additional_kwargs: { hide_from_ui: true },
      } as Partial<Message>),
      ai("answer", {
        additional_kwargs: {
          reasoning_content: "secret reasoning",
        },
        tool_calls: [{ id: "1", name: "task", args: {} }],
      } as Partial<Message>),
      toolMsg("internal trace"),
    ];
    const raw = formatThreadAsJSON(makeThread(), messages);
    const parsed = JSON.parse(raw) as {
      messages: { type: string; tool_calls?: unknown[] }[];
    };

    expect(parsed.messages).toHaveLength(2);
    expect(parsed.messages.every((m) => m.type !== "tool")).toBe(true);
    expect(raw).not.toContain("secret reminder");
    expect(raw).not.toContain("secret reasoning");
    expect(raw).not.toContain("internal trace");
    expect(raw).not.toContain("tool_calls");
  });

  it("strips inline <think>...</think> wrappers from content", () => {
    // bytedance/deer-flow#3131 review: JSON export must run the same
    // sanitiser the Markdown path uses so inline reasoning never leaks
    // even when `includeReasoning` is left at its default false.
    const message = ai("<think>internal monologue</think>visible answer", {
      id: "ai-1",
    } as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message]);
    expect(raw).not.toContain("internal monologue");
    expect(raw).not.toContain("<think>");
    expect(raw).toContain("visible answer");
  });

  it("strips content-array thinking blocks from content", () => {
    const message = ai("placeholder", {
      id: "ai-2",
      content: [
        { type: "thinking", thinking: "hidden reasoning step" },
        { type: "text", text: "final visible text" },
      ],
    } as unknown as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message]);
    expect(raw).not.toContain("hidden reasoning step");
    expect(raw).toContain("final visible text");
  });

  it("strips <uploaded_files> markers from content", () => {
    const message = human(
      "real prompt\n<uploaded_files>\n/mnt/user-data/uploads/secret.pdf\n</uploaded_files>",
      { id: "h-clean" } as Partial<Message>,
    );
    const raw = formatThreadAsJSON(makeThread(), [message]);
    expect(raw).not.toContain("<uploaded_files>");
    expect(raw).not.toContain("secret.pdf");
    expect(raw).toContain("real prompt");
  });

  it("drops AI messages that sanitise to empty content", () => {
    // Pure-reasoning AI fragments (no visible text, no tool calls) should
    // not survive as `{content: ""}` rows in the export.
    const message = ai("<think>only thinking, no answer</think>", {
      id: "ai-3",
    } as Partial<Message>);
    const raw = formatThreadAsJSON(makeThread(), [message]);
    const parsed = JSON.parse(raw) as { messages: unknown[] };
    expect(parsed.messages).toHaveLength(0);
  });
});
