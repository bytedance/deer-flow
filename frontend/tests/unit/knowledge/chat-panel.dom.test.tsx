/**
 * Right-column knowledge chat panel (spec §4.5/§4.6/§4.7/§5.2): binds the
 * current kb via ``context.kb_id`` + ``agent_name: "rag"``, isolates its
 * threads behind ``metadata.kb_id``, offers a kb-scoped history popover, a
 * deep-retrieval toggle, citation footers, and an expand-to-full-page entry.
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

const mockUseThreadStream = rs.fn();
const mockUseInfiniteThreads = rs.fn();
const mockSendMessage = rs.fn();
const mockDeleteThread = rs.fn();
const mockUseModels = rs.fn();
const mockUseAgentsApiEnabled = rs.fn();

rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => mockUseAgentsApiEnabled(),
}));

rs.mock("@/core/threads/hooks", () => ({
  useThreadStream: (options: unknown) => mockUseThreadStream(options),
  useInfiniteThreads: (params?: unknown) => mockUseInfiniteThreads(params),
  useDeleteThread: () => ({ mutate: mockDeleteThread }),
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => mockUseModels(),
}));

// 面板挂载时会向外壳登记「当前跟哪个会话」(spec §10.3),但那件事由
// activity-context / agent-pet 两套用例覆盖(含注册值),这里只测 kb 绑定与流,
// 不为了它把每条 render 都包一层 ActivityProvider。
rs.mock("@/core/threads/activity-context", () => ({
  useRegisterActivity: () => undefined,
}));

let capturedMessageListProps: Record<string, unknown> | null = null;

rs.mock("@/components/workspace/messages", () => ({
  MessageList: (props: Record<string, unknown>) => {
    capturedMessageListProps = props;
    // 假滚动层 + human turn 节点（2026-09-08 刻度轨接线）：面板侧 active
    // 追踪与跳转都挂这两个钩子（data-slot 视口 / data-human-turn 全局序号），
    // mock 环境以同结构节点代替真实 MessageList 渲染。
    return (
      <div data-testid="message-list">
        <div data-slot="scroll-area-viewport">
          <div data-human-turn="0" />
          <div data-human-turn="1" />
        </div>
      </div>
    );
  },
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM: 120,
}));

import { KnowledgeChatPanel } from "@/components/workspace/knowledge/chat-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeBase } from "@/core/knowledge/types";

const KB: KnowledgeBase = {
  id: "kb-1",
  owner_id: "user-1",
  name: "产品知识库",
  description: "",
  visibility: "private",
  created_at: "2026-08-01T10:00:00Z",
};

const KB2: KnowledgeBase = { ...KB, id: "kb-2", name: "第二库" };

function makeThread(threadId: string, kbId: string | null, title: string) {
  return {
    thread_id: threadId,
    created_at: "2026-08-09T09:00:00Z",
    updated_at: "2026-08-09T10:00:00Z",
    status: "idle",
    metadata: kbId ? { kb_id: kbId } : {},
    values: { title, messages: [] },
  };
}

const KB_THREAD = makeThread("thread-kb1-a", "kb-1", "如何上传文档");
const OTHER_KB_THREAD = makeThread("thread-kb2-a", "kb-2", "别的库会话");
const PLAIN_THREAD = makeThread("thread-plain", null, "普通会话");

const MODELS = [
  {
    name: "deepseek-v4-flash",
    model: "deepseek-v4-flash",
    display_name: "DeepSeek V4 Flash",
    description: null,
    supports_thinking: true,
    supports_reasoning_effort: false,
    context_window: 128000,
  },
  {
    name: "qwen-plus",
    model: "qwen-plus-latest",
    display_name: "Qwen Plus",
    description: null,
    supports_thinking: true,
    supports_reasoning_effort: true,
    context_window: 200000,
  },
];

function makeThreadState(messages: unknown[] = []) {
  return {
    messages,
    isLoading: false,
    error: null,
    values: {},
    stop: rs.fn(),
  };
}

function renderPanel(
  kb: KnowledgeBase | null = KB,
  props?: Partial<Parameters<typeof KnowledgeChatPanel>[0]>,
) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <KnowledgeChatPanel kb={kb} {...props} />
    </I18nContext.Provider>,
  );
}

function rerenderPanel(
  view: ReturnType<typeof renderPanel>,
  kb: KnowledgeBase | null,
  props?: Partial<Parameters<typeof KnowledgeChatPanel>[0]>,
) {
  view.rerender(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <KnowledgeChatPanel kb={kb} {...props} />
    </I18nContext.Provider>,
  );
}

beforeEach(() => {
  capturedMessageListProps = null;
  // The real sendMessage fires options.onSent once the in-flight guard passes;
  // the human-input handler reports success through that callback.
  mockSendMessage.mockImplementation(
    async (
      _threadId: string,
      _message: unknown,
      _extraContext?: unknown,
      options?: { onSent?: () => void },
    ) => {
      options?.onSent?.();
    },
  );
  mockUseThreadStream.mockImplementation(() => ({
    thread: makeThreadState(),
    sendMessage: mockSendMessage,
  }));
  mockUseInfiniteThreads.mockReturnValue({
    data: { pages: [[KB_THREAD, OTHER_KB_THREAD, PLAIN_THREAD]] },
  });
  mockUseModels.mockReturnValue({ models: MODELS, tokenUsageEnabled: false, isLoading: false, error: null });
  mockUseAgentsApiEnabled.mockReturnValue({ enabled: true, isLoading: false });
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function latestStreamOptions() {
  const calls = mockUseThreadStream.mock.calls;
  return calls.at(-1)?.[0] as {
    threadId?: string;
    context: Record<string, unknown>;
    onStart?: (threadId: string) => void;
  };
}

describe("KnowledgeChatPanel", () => {
  it("shows guidance and disables the input when no kb is selected (spec §4.5)", () => {
    renderPanel(null);
    expect(screen.getByText("未选择知识库")).toBeTruthy();
    expect(screen.getByText("请先在左侧选择要检索的知识库")).toBeTruthy();
    const textarea = screen.getByPlaceholderText("向当前知识库提问…");
    expect(textarea).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "发送" })).toHaveProperty("disabled", true);
  });

  it("binds the current kb through stream context (agent_name + kb_id)", () => {
    renderPanel();
    const options = latestStreamOptions();
    expect(options.context.agent_name).toBe("rag");
    expect(options.context.kb_id).toBe("kb-1");
    expect(options.threadId).toBeUndefined();
  });

  it("sends the draft through sendMessage with the current thread id", () => {
    renderPanel();
    const textarea = screen.getByPlaceholderText("向当前知识库提问…");
    fireEvent.change(textarea, { target: { value: "这个产品支持哪些格式？" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(mockSendMessage).toHaveBeenCalledTimes(1);
    const [threadId, message, , options] = mockSendMessage.mock.calls[0] as [
      string,
      { text: string; files: unknown[] },
      unknown,
      { additionalKwargs?: Record<string, unknown> },
    ];
    expect(typeof threadId).toBe("string");
    expect(threadId.length).toBeGreaterThan(0);
    expect(message.text).toBe("这个产品支持哪些格式？");
    expect(message.files).toEqual([]);
    // The turn carries the bound kb as a provider-qualified scope snapshot
    // (#5238): retrieval reads this, not the run context.
    expect(options?.additionalKwargs?.knowledge_scope).toEqual({
      version: 1,
      mode: "selected",
      dataset_ids: ["local:kb-1"],
      display: { datasets: [{ id: "local:kb-1", name: "产品知识库" }] },
    });
    expect(textarea).toHaveProperty("value", "");
  });

  it("lists only current-kb threads in the history popover, grouped by date", () => {
    renderPanel();
    const trigger = screen.getByRole("button", { name: "历史会话" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByText("如何上传文档")).toBeTruthy();
    expect(screen.queryByText("别的库会话")).toBeNull();
    expect(screen.queryByText("普通会话")).toBeNull();
    expect(screen.getByText("2026-08-09")).toBeTruthy();
    // 隐式滑条化（2026-09-08）：content 基类 overflow-y-auto 的老原生竖滑条
    // 退役——清单沉进 overlay ScrollArea（type="scroll"、停 2s 淡出）。
    const menu = screen.getByRole("menu");
    expect(menu.className).toContain("overflow-hidden");
    expect(menu.className).not.toContain("overflow-y-auto");
    expect(menu.querySelector("[data-slot='scroll-area']")).toBeTruthy();
  });

  it("caps the history list height so it cannot grow to the full interface", () => {
    // Spec 2026-09-24 §7.4: the old ceiling was Radix's *available* height — the trigger
    // sits at the very top of the right column, so that ceiling is the whole interface and
    // the menu stretched floor to ceiling. A fixed pixel cap (min(300px, available)) keeps
    // the low-viewport guarantee while ending the stretch.
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), {
      key: "ArrowDown",
    });
    const scroll = screen
      .getByRole("menu")
      .querySelector("[data-slot='scroll-area']")!;
    expect(scroll.className).toContain("min(300px");
  });

  it("loads the selected conversation from the history popover", () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByText("如何上传文档"));
    expect(latestStreamOptions().threadId).toBe("thread-kb1-a");
  });

  it("deletes a history conversation via its delete button WITHOUT selecting it", () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    // Only the current-kb thread is listed, so exactly one delete button.
    const deleteButton = screen.getByRole("button", { name: "删除会话" });
    fireEvent.click(deleteButton);
    expect(mockDeleteThread).toHaveBeenCalledTimes(1);
    const args = mockDeleteThread.mock.calls[0]![0] as {
      threadId: string;
      onDeleted?: () => void;
    };
    expect(args.threadId).toBe("thread-kb1-a");
    // Not the open conversation → no reset callback.
    expect(args.onDeleted).toBeUndefined();
    // The row must not become the selected conversation.
    expect(latestStreamOptions().threadId).toBeUndefined();
  });

  it("resets to a fresh conversation when the OPEN conversation is deleted", () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByText("如何上传文档"));
    expect(latestStreamOptions().threadId).toBe("thread-kb1-a");
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("button", { name: "删除会话" }));
    const args = mockDeleteThread.mock.calls[0]![0] as {
      threadId: string;
      onDeleted?: () => void;
    };
    expect(args.threadId).toBe("thread-kb1-a");
    expect(typeof args.onDeleted).toBe("function");
    act(() => args.onDeleted!());
    expect(latestStreamOptions().threadId).toBeUndefined();
  });

  it("resets to a fresh thread via the new-chat button after picking history", () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByText("如何上传文档"));
    expect(latestStreamOptions().threadId).toBe("thread-kb1-a");
    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(latestStreamOptions().threadId).toBeUndefined();
  });

  // 2026-10-06 缺陷批：切库即新对话（还原 `2711a35a2` 的重置，`52b0dd76d` 重构时误删）。
  it("starts a fresh conversation when the knowledge base is switched", () => {
    const view = renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByText("如何上传文档"));
    expect(latestStreamOptions().threadId).toBe("thread-kb1-a");
    rerenderPanel(view, KB2);
    expect(latestStreamOptions().threadId).toBeUndefined();
  });

  // 位序守卫：重置 effect 必须先于 requestedThreadId 深链 effect——先重置、后选中，深链才能胜出。
  it("keeps the deep-linked thread selected under the switch reset (effect ordering)", () => {
    renderPanel(KB, { requestedThreadId: "thread-kb1-a" });
    expect(latestStreamOptions().threadId).toBe("thread-kb1-a");
  });

  it("adopts the backend-created thread id via onStart (metadata.kb_id thread)", () => {
    renderPanel();
    act(() => {
      latestStreamOptions().onStart?.("created-thread-1");
    });
    expect(latestStreamOptions().threadId).toBe("created-thread-1");
  });

  it("expands the active conversation to the full rag chat page", () => {
    renderPanel();
    expect(
      screen.getByRole("link", { name: "在完整页面中打开" }).getAttribute("aria-disabled"),
    ).toBe("true");
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByText("如何上传文档"));
    const link = screen.getByRole("link", { name: "在完整页面中打开" });
    expect(link.getAttribute("href")).toBe("/workspace/agents/rag/chats/thread-kb1-a");
  });

  it("keeps the expand link disabled when the agents feature is off, even for a persisted thread", () => {
    mockUseAgentsApiEnabled.mockReturnValue({ enabled: false, isLoading: false });
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "历史会话" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByText("如何上传文档"));
    const link = screen.getByRole("link", { name: "在完整页面中打开" });
    expect(link.getAttribute("aria-disabled")).toBe("true");
    expect(link.getAttribute("href")).toBe("#");
  });

  it("renders citation cards below assistant answers via the message footer (spec §4.6)", () => {
    const toolMessage = {
      id: "tool-1",
      type: "tool",
      name: "knowledge_search",
      content: JSON.stringify({
        results: [
          {
            chunk_id: "doc-1#0000",
            doc_name: "产品手册.pdf",
            page: 3,
            heading_path: [],
            text: "知识库系统将非结构化文档转化为可检索的知识资产。",
            score: 0.9,
          },
        ],
      }),
    };
    const aiMessage = { id: "ai-1", type: "ai", content: "支持 PDF 与 Markdown [1]" };
    mockUseThreadStream.mockImplementation(() => ({
      thread: makeThreadState([
        { id: "human-1", type: "human", content: "支持哪些格式？" },
        toolMessage,
        aiMessage,
      ]),
      sendMessage: mockSendMessage,
    }));
    renderPanel();
    expect(capturedMessageListProps).not.toBeNull();
    const renderFooter = capturedMessageListProps!.renderMessageFooter as (
      message: unknown,
    ) => React.ReactNode;
    cleanup();
    render(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        {renderFooter(aiMessage)}
      </I18nContext.Provider>,
    );
    expect(screen.getByText(/参考来源 · 1/)).toBeTruthy();
    // P2: collapsed by default — the doc name appears after expanding
    expect(screen.queryByText("产品手册.pdf")).toBeNull();
    fireEvent.click(screen.getByText(/参考来源 · 1/));
    expect(screen.getByText("产品手册.pdf")).toBeTruthy();
  });

  it("wires onSubmitHumanInput so clarification cards stay interactive", async () => {
    renderPanel();
    expect(capturedMessageListProps).not.toBeNull();
    const onSubmitHumanInput = capturedMessageListProps!
      .onSubmitHumanInput as (
      request: unknown,
      response: unknown,
    ) => Promise<unknown>;
    expect(typeof onSubmitHumanInput).toBe("function");

    const request = {
      version: 1,
      kind: "human_input_request",
      source: "ask_clarification",
      request_id: "req-1",
      question: "想查什么？",
      input_mode: "free_text",
    };
    const response = {
      version: 1,
      kind: "human_input_response",
      source: "ask_clarification",
      request_id: "req-1",
      response_kind: "text",
      value: "三路检索",
    };
    let result: unknown;
    await act(async () => {
      result = await onSubmitHumanInput(request, response);
    });
    expect(result).toBe(true);
    expect(mockSendMessage).toHaveBeenCalledTimes(1);
    const [, message, extraContext, options] = mockSendMessage.mock.calls[0] as [
      string,
      { text: string; files: unknown[] },
      Record<string, unknown>,
      { additionalKwargs: Record<string, unknown> },
    ];
    expect(message.files).toEqual([]);
    expect(message.text).toContain("三路检索");
    expect(extraContext.agent_name).toBe("rag");
    expect(options.additionalKwargs.hide_from_ui).toBe(true);
    expect(options.additionalKwargs.human_input_response).toEqual(response);
  });
});

// ── P6 检索联动（2026-08-15 spec §9 通道二）：最新一轮提问+引用上报 page 层 ──

describe("KnowledgeChatPanel model selector", () => {
  it("shows the first configured model as the effective default and keeps context.model_name undefined", () => {
    renderPanel();
    // 未显式选择时：触发器显示后端默认（models[0]），context 保持 undefined
    // 让后端走 request → agent 配置 → 全局默认的解析链。
    expect(screen.getByRole("button", { name: "选择模型" }).textContent).toContain("DeepSeek V4 Flash");
    expect(latestStreamOptions().context.model_name).toBeUndefined();
  });

  it("writes the picked model into the stream context and persists it per kb", async () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "选择模型" }));
    fireEvent.click(await screen.findByText("Qwen Plus"));

    expect(latestStreamOptions().context.model_name).toBe("qwen-plus");
    expect(localStorage.getItem("rag-chat-model:kb-1")).toBe("qwen-plus");
    // 选择后弹层关闭、触发器显示新选择
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "选择模型" }).textContent).toContain("Qwen Plus");
  });

  it("restores the remembered model per kb and falls back to default when switching to an unremembered kb", () => {
    localStorage.setItem("rag-chat-model:kb-1", "qwen-plus");
    const utils = render(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <KnowledgeChatPanel kb={KB} />
      </I18nContext.Provider>,
    );
    expect(latestStreamOptions().context.model_name).toBe("qwen-plus");
    expect(screen.getByRole("button", { name: "选择模型" }).textContent).toContain("Qwen Plus");

    utils.rerender(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <KnowledgeChatPanel kb={{ ...KB, id: "kb-2", name: "第二库" }} />
      </I18nContext.Provider>,
    );
    // kb-2 没有记忆 → 回落默认显示，context 恢复 undefined
    expect(latestStreamOptions().context.model_name).toBeUndefined();
    expect(screen.getByRole("button", { name: "选择模型" }).textContent).toContain("DeepSeek V4 Flash");
  });
});
