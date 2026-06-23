/* @vitest-environment jsdom */

import type { BaseStream } from "@langchain/langgraph-sdk/react";
import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";


vi.mock("@/components/ai-elements/conversation", () => ({
  Conversation: ({
    children,
  }: React.PropsWithChildren) => React.createElement("div", null, children),
  ConversationContent: ({
    children,
  }: React.PropsWithChildren) => React.createElement("div", null, children),
}));

vi.mock("@/components/genui", () => ({
  GenUIBlockList: ({ blockIds }: { blockIds?: string[] }) =>
    React.createElement(
      "div",
      { "data-testid": "block-list" },
      `BLOCK:${blockIds?.join(",") ?? ""}`,
    ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.PropsWithChildren<Record<string, unknown>>) =>
    React.createElement("button", props, children),
}));

vi.mock("@/core/agents", () => ({
  useAgent: () => ({
    agent: undefined,
  }),
}));

vi.mock("@/core/genui", () => ({
  submitInteraction: vi.fn(),
}));

vi.mock("@/core/genui/sse-recovery", () => ({
  GenUISSEManager: vi.fn().mockImplementation(() => ({
    recoverBlocks: vi.fn().mockResolvedValue(undefined),
    scheduleReconnect: vi.fn(),
    disconnect: vi.fn(),
    get connected() {
      return false;
    },
  })),
}));

vi.mock("@/core/genui/history", async () => {
  const actual = await vi.importActual("@/core/genui/history");
  return {
    ...actual,
    fetchResolvedBlockHistory: vi.fn().mockResolvedValue({
      blocks: [],
      blockIdsByMessageKey: new Map(),
      duplicatedRawBlockIds: new Set(),
    }),
  };
});

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "Loading",
        loadMore: "Load more",
      },
      subtasks: {
        executing: (count: number) => `Executing ${count}`,
      },
      uploads: {
        uploadingFiles: "Uploading files",
      },
      toolCalls: {
        generationProcess: "Generation Process",
        generationProcessSteps: (count: number) => `${count} steps`,
      },
      tokenUsage: {
        sharedAttribution: "Shared attribution",
      },
    },
  }),
}));

vi.mock("@/core/messages/usage-model", () => ({
  buildTokenDebugSteps: () => [],
}));

vi.mock("@/core/rehype", () => ({
  useRehypeSplitWordsIntoSpans: () => [],
}));

vi.mock("@/core/tasks/context", () => ({
  useUpdateSubtask: () => vi.fn(),
}));

vi.mock("@/components/workspace/messages/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) =>
    React.createElement("div", null, content),
}));

vi.mock("@/components/workspace/messages/message-group", () => ({
  MessageGroup: ({ messages }: { messages: Array<{ id?: string }> }) =>
    React.createElement(
      "div",
      null,
      `GROUP:${messages.map((message) => message.id ?? "").join(",")}`,
    ),
}));

vi.mock("@/components/workspace/messages/message-list-item", () => ({
  MessageListItem: ({
    message,
  }: {
    message: { id?: string; type: string; content?: unknown };
  }) =>
    React.createElement(
      "div",
      { "data-testid": "message-item" },
      `${message.type.toUpperCase()}:${message.id ?? ""}`,
    ),
}));

vi.mock("@/components/workspace/messages/message-token-usage", () => ({
  MessageTokenUsageDebugList: () => null,
  MessageTokenUsageList: () => null,
}));

vi.mock("@/components/workspace/messages/retrieval-sources", () => ({
  RetrievalSources: () => null,
}));

vi.mock("@/components/workspace/messages/skeleton", () => ({
  MessageListSkeleton: () => React.createElement("div", null, "skeleton"),
}));

vi.mock("@/components/workspace/messages/stream-tier-notice-banner", () => ({
  StreamTierNoticeBanner: () => null,
}));

vi.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));

vi.mock("@/components/workspace/artifacts/artifact-file-list", () => ({
  ArtifactFileList: () => null,
}));

vi.mock("@/components/workspace/copy-button", () => ({
  CopyButton: () => null,
}));

vi.mock("@/components/workspace/streaming-indicator", () => ({
  StreamingIndicator: () => React.createElement("div", null, "STREAMING"),
}));

import { MessageList } from "@/components/workspace/messages/message-list";
import { fetchResolvedBlockHistory } from "@/core/genui/history";
import { useBlockStore, type UIBlock } from "@/core/genui/store";
import type { AgentThreadState } from "@/core/threads";

function makeBlock(block_id: string, overrides?: Partial<UIBlock>): UIBlock {
  return {
    schema_version: "1.0",
    type: "ui_block",
    action: "create",
    block_id,
    component: "table",
    props: {},
    interactive: false,
    ...overrides,
  };
}

function makeThread(
  isLoading: boolean,
  messages: Array<Record<string, unknown>>,
): BaseStream<AgentThreadState> {
  return {
    messages,
    isLoading,
    isThreadLoading: false,
  } as unknown as BaseStream<AgentThreadState>;
}

describe("MessageList standalone block placement", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    vi.mocked(fetchResolvedBlockHistory).mockResolvedValue({
      blocks: [],
      blockIdsByMessageKey: new Map(),
      duplicatedRawBlockIds: new Set(),
    });
    useBlockStore.getState().reset();
    useBlockStore.setState({
      activeThreadId: "thread-1",
      blocks: new Map([["old-block", makeBlock("old-block")]]),
      interactions: new Map(),
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
    useBlockStore.getState().reset();
  });

  it("keeps pre-existing standalone blocks after messages when submit starts streaming", async () => {
    const baseMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "生成日报" }],
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, baseMessages),
        }),
      );
    });

    expect(container.textContent?.indexOf("HUMAN:human-1")).toBeLessThan(
      container.textContent?.indexOf("BLOCK:old-block") ?? Number.POSITIVE_INFINITY,
    );

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(true, baseMessages),
        }),
      );
    });

    await React.act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent?.indexOf("HUMAN:human-1")).toBeLessThan(
      container.textContent?.indexOf("BLOCK:old-block") ?? Number.POSITIVE_INFINITY,
    );
  });

  it("moves previous-turn standalone blocks back above the new turn once live messages arrive", async () => {
    const previousMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "上一轮日报" }],
      },
    ];

    const nextTurnMessages = [
      ...previousMessages,
      {
        type: "human" as const,
        id: "human-2",
        content: [{ type: "text" as const, text: "再来一份日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: [{ type: "text" as const, text: "请填写日报参数后提交。" }],
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, previousMessages),
        }),
      );
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(true, previousMessages),
        }),
      );
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, nextTurnMessages),
        }),
      );
    });

    expect(container.textContent?.indexOf("BLOCK:old-block")).toBeLessThan(
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.POSITIVE_INFINITY,
    );
  });

  it("keeps defect workflow todo blocks at the start of the message stream", async () => {
    useBlockStore.setState({
      blocks: new Map([
        [
          "defect-workflow-closure:todo-list:thread-1",
          makeBlock("defect-workflow-closure:todo-list:thread-1", {
            component: "defect-workflow-todo-list",
            metadata: {
              source: "agent-home",
              agent_name: "defect-workflow-closure",
            },
          }),
        ],
      ]),
      interactions: new Map(),
    });

    const previousMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "上一轮问题" }],
      },
    ];

    const nextTurnMessages = [
      ...previousMessages,
      {
        type: "human" as const,
        id: "human-2",
        content: [{ type: "text" as const, text: "选择的缺陷设备ID是什么" }],
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: [{ type: "text" as const, text: "设备ID是 2067..." }],
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, previousMessages),
        }),
      );
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(true, previousMessages),
        }),
      );
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, nextTurnMessages),
        }),
      );
    });

    const defectBlockIndex =
      container.textContent?.indexOf("BLOCK:defect-workflow-closure:todo-list:thread-1") ?? -1;
    const firstMessageIndex =
      container.textContent?.indexOf("HUMAN:human-1") ?? Number.POSITIVE_INFINITY;
    const nextTurnIndex =
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.POSITIVE_INFINITY;

    expect(defectBlockIndex).toBeGreaterThanOrEqual(0);
    expect(defectBlockIndex).toBeLessThan(firstMessageIndex);
    expect(defectBlockIndex).toBeLessThan(nextTurnIndex);
  });

  it("keeps blocks near their first processing turn when they later become standalone", async () => {
    const firstTurnMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "第一轮日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-1",
        tool_call_id: "tool-call-1",
        content:
          "UI component 'card' (create) rendered successfully. block_id=old-block",
      },
    ];

    const secondTurnMessages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "第一轮日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "human" as const,
        id: "human-2",
        content: [{ type: "text" as const, text: "第二轮日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: [{ type: "text" as const, text: "请提交第一步表单" }],
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, firstTurnMessages),
        }),
      );
    });

    // Panel label visible, output block renders outside the collapsed panel
    expect(
      container.textContent?.indexOf("Generation Process"),
    ).toBeLessThan(
      container.textContent?.indexOf("BLOCK:old-block") ?? Number.POSITIVE_INFINITY,
    );

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, secondTurnMessages),
        }),
      );
    });

    // old-block is a standalone output block, visible outside the collapsed panel
    expect(container.textContent).toContain("Generation Process");
    expect(container.textContent).toContain("BLOCK:old-block");

    const panelIndex =
      container.textContent?.indexOf("Generation Process") ?? -1;
    const oldBlockIndex = container.textContent?.indexOf("BLOCK:old-block") ?? -1;
    const secondTurnIndex =
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.POSITIVE_INFINITY;

    expect(panelIndex).toBeGreaterThanOrEqual(0);
    expect(oldBlockIndex).toBeGreaterThan(panelIndex);
    expect(oldBlockIndex).toBeLessThan(secondTurnIndex);
  });

  it("renders separate historical results when two rounds reused the same raw block id", async () => {
    useBlockStore.setState({
      blocks: new Map(),
      interactions: new Map(),
    });

    const duplicateBlockContent = (title: string) =>
      `UI component 'card' (create) rendered successfully. block_id=daily-report-chart\n<!--ui_block:{"schema_version":"1.0","type":"ui_block","action":"create","block_id":"daily-report-chart","component":"card","props":{"title":"${title}"},"interactive":false}-->`;

    const messages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "first turn" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-1",
        tool_call_id: "tool-call-1",
        content: duplicateBlockContent("Round 1"),
      },
      {
        type: "human" as const,
        id: "human-2",
        content: [{ type: "text" as const, text: "second turn" }],
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: "",
        tool_calls: [{ id: "tool-call-2", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-2",
        tool_call_id: "tool-call-2",
        content: duplicateBlockContent("Round 2"),
      },
    ];

    vi.mocked(fetchResolvedBlockHistory).mockResolvedValue({
      blocks: [
        {
          schema_version: "1.0",
          type: "ui_block" as const,
          action: "create" as const,
          block_id: "daily-report-chart__1",
          component: "card",
          props: { title: "Round 1" },
          interactive: false,
        },
        {
          schema_version: "1.0",
          type: "ui_block" as const,
          action: "create" as const,
          block_id: "daily-report-chart__2",
          component: "card",
          props: { title: "Round 2" },
          interactive: false,
        },
      ],
      blockIdsByMessageKey: new Map([
        ["tool-1", ["daily-report-chart__1"]],
        ["tool-2", ["daily-report-chart__2"]],
      ]),
      duplicatedRawBlockIds: new Set(["daily-report-chart"]),
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, messages),
        }),
      );
    });

    expect(container.textContent).toContain("BLOCK:daily-report-chart__1");
    expect(container.textContent).toContain("BLOCK:daily-report-chart__2");
    expect(
      container.textContent?.indexOf("BLOCK:daily-report-chart__1"),
    ).toBeLessThan(
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.POSITIVE_INFINITY,
    );
    expect(
      container.textContent?.indexOf("BLOCK:daily-report-chart__2"),
    ).toBeGreaterThan(
      container.textContent?.indexOf("HUMAN:human-2") ?? Number.NEGATIVE_INFINITY,
    );
  });

  it("hides transient intent/summary once a visible report block is available", async () => {
    useBlockStore.setState({
      blocks: new Map([
        [
          "report-block-1",
          makeBlock("report-block-1", {
            component: "markdown",
            props: { content: "# 设备运行日报\n\n这是最终报告。" },
          }),
        ],
      ]),
      interactions: new Map(),
    });

    const messages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "生成日报" }],
      },
      {
        type: "ai" as const,
        id: "intent-1",
        name: "intent",
        content: "SESSION INTENT\n- generate daily report",
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-1",
        tool_call_id: "tool-call-1",
        content:
          "UI component 'markdown' (create) rendered successfully. block_id=report-block-1\n<!--ui_block:{\"schema_version\":\"1.0\",\"type\":\"ui_block\",\"action\":\"create\",\"block_id\":\"report-block-1\",\"component\":\"markdown\",\"props\":{\"content\":\"# 设备运行日报\\n\\n这是最终报告。\"},\"interactive\":false}-->",
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(true, messages),
        }),
      );
    });

    expect(container.textContent).toContain("BLOCK:report-block-1");
    expect(container.textContent).not.toContain("AI:intent-1");
  });

  it("suppresses assistant markdown that duplicates a rendered markdown block", async () => {
    useBlockStore.setState({
      blocks: new Map([
        [
          "report-block-2",
          makeBlock("report-block-2", {
            component: "markdown",
            props: {
              content:
                "# 设备运行日报\n\n## 概览\n\n这是最终日报内容，用于验证不会重复显示。",
            },
          }),
        ],
      ]),
      interactions: new Map(),
    });

    const messages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "生成日报" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tool-call-1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-1",
        tool_call_id: "tool-call-1",
        content:
          "UI component 'markdown' (create) rendered successfully. block_id=report-block-2\n<!--ui_block:{\"schema_version\":\"1.0\",\"type\":\"ui_block\",\"action\":\"create\",\"block_id\":\"report-block-2\",\"component\":\"markdown\",\"props\":{\"content\":\"# 设备运行日报\\n\\n## 概览\\n\\n这是最终日报内容，用于验证不会重复显示。\"},\"interactive\":false}-->",
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content:
          "# 设备运行日报\n\n## 概览\n\n这是最终日报内容，用于验证不会重复显示。",
      },
    ];

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, messages),
        }),
      );
    });

    expect(container.textContent).toContain("BLOCK:report-block-2");
    expect(container.textContent).not.toContain("AI:ai-2");
  });

  it("renders active KPI form block only once at the correct location", async () => {
    useBlockStore.setState({
      blocks: new Map([
        [
          "form-kpi",
          makeBlock("form-kpi", {
            component: "form",
            interactive: true,
            callback_id: "daily-report-confirm",
          }),
        ],
      ]),
      interactions: new Map(),
    });

    const messages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "form submission payload" }],
      },
      {
        type: "ai" as const,
        id: "ai-1",
        content: "",
        tool_calls: [{ id: "tc-1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-1",
        tool_call_id: "tc-1",
        content:
          "UI component 'form' (create) rendered successfully. block_id=form-kpi",
      },
      {
        type: "ai" as const,
        id: "ai-2",
        content: [{ type: "text" as const, text: "请选择要包含的KPI指标" }],
      },
    ];

    vi.mocked(fetchResolvedBlockHistory).mockResolvedValue({
      blocks: [
        {
          schema_version: "1.0",
          type: "ui_block" as const,
          action: "create" as const,
          block_id: "form-kpi",
          component: "form",
          props: { title: "KPI确认" },
          interactive: true,
          callback_id: "daily-report-confirm",
        },
      ],
      blockIdsByMessageKey: new Map([["tool-1", ["form-kpi"]]]),
      duplicatedRawBlockIds: new Set(),
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, messages),
        }),
      );
    });

    // Form block must appear exactly once
    const blockMatches =
      container.textContent?.match(/BLOCK:form-kpi/g) ?? [];
    expect(blockMatches).toHaveLength(1);

    // Form block must appear after the processing panel label
    const panelIndex =
      container.textContent?.indexOf("Generation Process") ?? -1;
    const formIndex =
      container.textContent?.indexOf("BLOCK:form-kpi") ?? -1;
    expect(panelIndex).toBeGreaterThanOrEqual(0);
    expect(formIndex).toBeGreaterThan(panelIndex);

    // Guidance text at the end of the stream (no human response yet) should be visible
    // — user needs to read it to know what to do next.
    expect(container.textContent).toContain("AI:ai-2");
  });

  it("renders only the current-turn form and hides previously-submitted forms after page refresh", async () => {
    // Simulate page refresh: multiple rounds of history loaded from backend,
    // interactions map is empty (no submission state persisted).
    const blockRound1Form = makeBlock("form-round1", {
      component: "form",
      interactive: true,
      callback_id: "daily-report-basic",
      interaction_status: "submitted",
      props: { title: "基础参数" },
    });
    const blockMarkdown = makeBlock("markdown-report", {
      component: "markdown",
      props: { content: "# 设备运行日报\n\n报告内容" },
    });
    const blockExport = makeBlock("export-form", {
      component: "form",
      interactive: true,
      functional_interaction: true,
      callback_id: "export-report",
      props: { title: "导出" },
    });
    const blockRound2Form = makeBlock("form-round2", {
      component: "form",
      interactive: true,
      callback_id: "daily-report-kpi",
      props: { title: "KPI确认" },
    });

    useBlockStore.setState({
      blocks: new Map([
        ["form-round1", blockRound1Form],
        ["markdown-report", blockMarkdown],
        ["export-form", blockExport],
        ["form-round2", blockRound2Form],
      ]),
      interactions: new Map(), // page refresh — no interaction state
    });

    // Full daily report history spanning Round 1 → Round 2 KPI form
    const messages = [
      // Round 1: ask for daily report
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "生成日报" }],
      },
      // Round 1: processing creates basic form
      {
        type: "ai" as const,
        id: "ai-round1",
        content: "",
        tool_calls: [{ id: "tc-round1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-round1",
        tool_call_id: "tc-round1",
        content:
          "UI component 'form' (create) rendered successfully. block_id=form-round1",
      },
      // Round 1: guidance text (should be hidden after submission happened)
      {
        type: "ai" as const,
        id: "ai-guide1",
        content: [{ type: "text" as const, text: "请填写日报参数后提交" }],
      },
      // Round 1: human submits form
      {
        type: "human" as const,
        id: "human-submit1",
        content: [{ type: "text" as const, text: "提交的KPI数据..." }],
      },
      // Round 1 cont: processing creates markdown + export form
      {
        type: "ai" as const,
        id: "ai-bash",
        content: "",
        tool_calls: [{ id: "tc-bash", name: "bash", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-bash",
        tool_call_id: "tc-bash",
        content: "execution complete",
      },
      // Consecutive processing: render_ui markdown
      {
        type: "ai" as const,
        id: "ai-md",
        content: "",
        tool_calls: [{ id: "tc-md", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-md",
        tool_call_id: "tc-md",
        content:
          "UI component 'markdown' (create) rendered successfully. block_id=markdown-report",
      },
      // Consecutive processing: render_ui export form
      {
        type: "ai" as const,
        id: "ai-export",
        content: "",
        tool_calls: [{ id: "tc-export", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-export",
        tool_call_id: "tc-export",
        content:
          "UI component 'form' (create) rendered successfully. block_id=export-form",
      },
      // Round 2: human submits export or next prompt
      {
        type: "human" as const,
        id: "human-round2",
        content: [{ type: "text" as const, text: "继续" }],
      },
      // Round 2: processing creates KPI form
      {
        type: "ai" as const,
        id: "ai-round2",
        content: "",
        tool_calls: [{ id: "tc-round2", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-round2",
        tool_call_id: "tc-round2",
        content:
          "UI component 'form' (create) rendered successfully. block_id=form-round2",
      },
      // Round 2: guidance text (user hasn't responded yet, should be visible)
      {
        type: "ai" as const,
        id: "ai-guide2",
        content: [{ type: "text" as const, text: "请选择要包含的KPI指标" }],
      },
    ];

    vi.mocked(fetchResolvedBlockHistory).mockResolvedValue({
      blocks: [blockRound1Form, blockMarkdown, blockExport, blockRound2Form],
      blockIdsByMessageKey: new Map([
        ["tool-round1", ["form-round1"]],
        ["tool-md", ["markdown-report"]],
        ["tool-export", ["export-form"]],
        ["tool-round2", ["form-round2"]],
      ]),
      duplicatedRawBlockIds: new Set(),
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, messages),
        }),
      );
    });

    // Only Round 2's KPI form should be visible
    expect(container.textContent).toContain("BLOCK:form-round2");
    // Round 1 submitted form should NOT appear (unsubmitted interactive form from past)
    expect(container.textContent).not.toContain("BLOCK:form-round1");
    // Output blocks (markdown + export) should appear (combined in one GenUIBlockList)
    expect(container.textContent).toContain("markdown-report");
    expect(container.textContent).toContain("export-form");
    // Round 1 guidance (between form creation and submission) should be hidden
    expect(container.textContent).not.toContain("AI:ai-guide1");
    // Round 2 guidance is the last assistant message — should be visible
    expect(container.textContent).toContain("AI:ai-guide2");

    // form-round2 must appear exactly once
    const round2Matches =
      container.textContent?.match(/BLOCK:form-round2/g) ?? [];
    expect(round2Matches).toHaveLength(1);
  });

  it("hides stale guidance text after form submission even when no visible human message follows", async () => {
    // Reproduces the bug where each form round leaves a stale "请填写..."
    // guidance line on screen because form submissions are hidden messages
    // (no visible human group to anchor against). After the form is submitted,
    // its preceding guidance text should be hidden — the next round's form
    // (or end of stream) is enough signal that the user has moved on.
    const round1Form = makeBlock("form-round1", {
      component: "form",
      interactive: true,
      callback_id: "daily-report-scope",
      props: { title: "Round 1" },
    });
    const round2Form = makeBlock("form-round2", {
      component: "form",
      interactive: true,
      callback_id: "daily-report-equipment",
      props: { title: "Round 2" },
    });

    useBlockStore.setState({
      blocks: new Map([
        ["form-round1", round1Form],
        ["form-round2", round2Form],
      ]),
      // Round 1 submitted, Round 2 still pending
      interactions: new Map([
        ["form-round1", { status: "submitted", submittedAt: Date.now() }],
      ]),
    });

    const messages = [
      {
        type: "human" as const,
        id: "human-1",
        content: [{ type: "text" as const, text: "生成日报" }],
      },
      // Round 1: render form
      {
        type: "ai" as const,
        id: "ai-round1",
        content: "",
        tool_calls: [{ id: "tc-round1", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-round1",
        tool_call_id: "tc-round1",
        content:
          "UI component 'form' (create) rendered successfully. block_id=form-round1",
      },
      // Round 1: stale guidance text (form already submitted — should be hidden)
      {
        type: "ai" as const,
        id: "ai-guide1",
        content: [{ type: "text" as const, text: "请填写日报参数后提交。" }],
      },
      // No visible human message — form submission is a hidden message that
      // never reaches getMessageGroups. The next visible group is the next
      // round's processing.
      // Round 2: render next form
      {
        type: "ai" as const,
        id: "ai-round2",
        content: "",
        tool_calls: [{ id: "tc-round2", name: "render_ui", args: {} }],
      },
      {
        type: "tool" as const,
        id: "tool-round2",
        tool_call_id: "tc-round2",
        content:
          "UI component 'form' (create) rendered successfully. block_id=form-round2",
      },
      // Round 2: guidance for the active (unsubmitted) form — should stay visible
      {
        type: "ai" as const,
        id: "ai-guide2",
        content: [{ type: "text" as const, text: "请选择设备后提交。" }],
      },
    ];

    vi.mocked(fetchResolvedBlockHistory).mockResolvedValue({
      blocks: [round1Form, round2Form],
      blockIdsByMessageKey: new Map([
        ["tool-round1", ["form-round1"]],
        ["tool-round2", ["form-round2"]],
      ]),
      duplicatedRawBlockIds: new Set(),
    });

    await React.act(async () => {
      root.render(
        React.createElement(MessageList, {
          threadId: "thread-1",
          thread: makeThread(false, messages),
        }),
      );
    });

    // Stale Round 1 guidance must be hidden (form already submitted)
    expect(container.textContent).not.toContain("AI:ai-guide1");
    // Round 2 guidance is for the active form — must stay visible
    expect(container.textContent).toContain("AI:ai-guide2");
  });
});
