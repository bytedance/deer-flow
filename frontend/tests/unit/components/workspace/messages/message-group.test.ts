import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  MessageGroup,
  scheduleToolLabel,
} from "@/components/workspace/messages/message-group";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

const artifactsMockState = rs.hoisted(() => ({
  autoOpen: false,
  autoSelect: false,
}));

rs.mock("@/components/workspace/artifacts", () => ({
  useArtifacts: () => ({
    artifacts: [],
    setArtifacts: () => undefined,
    selectedArtifact: null,
    autoSelect: artifactsMockState.autoSelect,
    select: () => undefined,
    deselect: () => undefined,
    open: false,
    autoOpen: artifactsMockState.autoOpen,
    setOpen: () => undefined,
  }),
}));

afterEach(() => {
  artifactsMockState.autoOpen = false;
  artifactsMockState.autoSelect = false;
  rs.restoreAllMocks();
});

describe("MessageGroup", () => {
  it("renders unresolved streaming assistant text before a tool call arrives", () => {
    const html = renderGroup(
      [
        {
          id: "ai-1",
          type: "ai",
          content: "I will inspect the source material first.",
        } as Message,
      ],
      { isLoading: true },
    );

    expect(html).toContain(">inspect</span>");
    expect(html).toContain(">source</span>");
    expect(html).toContain(">first.</span>");
  });

  it("renders assistant text attached to a tool-calling processing message", () => {
    const html = renderGroup([
      {
        id: "ai-1",
        type: "ai",
        content: "The browser action failed, so I will try another approach.",
        tool_calls: [
          {
            id: "call-1",
            name: "web_search",
            args: { query: "DeerFlow issue 4027" },
          },
        ],
      } as Message,
    ]);

    expect(html).toContain(
      "The browser action failed, so I will try another approach.",
    );
    expect(html).toContain("DeerFlow issue 4027");
  });

  it("keeps assistant text visible while older tool steps stay collapsed", () => {
    const html = renderGroup([
      {
        id: "ai-1",
        type: "ai",
        content: "The first tool failed; I will try a narrower search.",
        tool_calls: [
          {
            id: "call-1",
            name: "web_search",
            args: { query: "first hidden query" },
          },
        ],
      } as Message,
      {
        id: "tool-1",
        type: "tool",
        name: "web_search",
        tool_call_id: "call-1",
        content: "[]",
      } as Message,
      {
        id: "ai-2",
        type: "ai",
        content: "The second approach should reveal the missing context.",
        tool_calls: [
          {
            id: "call-2",
            name: "bash",
            args: {
              description: "Inspect message rendering",
              command: "rg assistantText frontend/src",
            },
          },
        ],
      } as Message,
    ]);

    expect(html).toContain(
      "The first tool failed; I will try a narrower search.",
    );
    expect(html).toContain(
      "The second approach should reveal the missing context.",
    );
    expect(html).not.toContain("first hidden query");
    expect(html).toContain("Inspect message rendering");
    expect(html).toContain("1 more step");
  });

  it("keeps content-only assistant text visible after a tool call while streaming", () => {
    const html = renderGroup(
      [
        {
          id: "ai-1",
          type: "ai",
          content: "I will inspect the current implementation.",
          tool_calls: [
            {
              id: "call-1",
              name: "read_file",
              args: { path: "message-group.tsx" },
            },
          ],
        } as Message,
        {
          id: "tool-1",
          type: "tool",
          name: "read_file",
          tool_call_id: "call-1",
          content: "file contents",
        } as Message,
        {
          id: "ai-2",
          type: "ai",
          content: "Here is the final streamed answer.",
        } as Message,
      ],
      { isLoading: true },
    );

    expect(html).toContain(">final</span>");
    expect(html).toContain(">streamed</span>");
    expect(html).toContain(">answer.</span>");
  });

  it("does not schedule artifact auto-open during render", () => {
    artifactsMockState.autoOpen = true;
    artifactsMockState.autoSelect = true;
    const timeoutSpy = rs.spyOn(globalThis, "setTimeout");
    const html = renderGroup(
      [
        {
          id: "ai-write",
          type: "ai",
          content: "",
          tool_calls: [
            {
              id: "call-write",
              name: "write_file",
              args: {
                path: "/mnt/user-data/outputs/report.md",
                content: "# Report",
              },
            },
          ],
        } as Message,
      ],
      { isLoading: true },
    );

    expect(html).toContain("/mnt/user-data/outputs/report.md");
    expect(timeoutSpy).not.toHaveBeenCalled();
  });

  it("renders streaming reasoning above the answer text of the same message", () => {
    const html = renderGroup(
      [
        {
          id: "ai-1",
          type: "ai",
          content: "Zephyr answer body.",
          additional_kwargs: {
            reasoning_content: "The user asked who I am, so I will summarize.",
          },
        } as Message,
      ],
      { isLoading: true },
    );

    expectRenderedInOrder(html, ["Thinking", ">Zephyr</span>"]);
  });

  it("renders streaming inline think reasoning above the answer text", () => {
    const html = renderGroup(
      [
        {
          id: "ai-1",
          type: "ai",
          content:
            "<think>\nThe user only said hello, so I will greet back.\n</think>\n\nZephyr answer body.",
        } as Message,
      ],
      { isLoading: true },
    );

    expectRenderedInOrder(html, ["Thinking", ">Zephyr</span>"]);
  });

  it("renders trailing reasoning above the answer text that follows a tool call", () => {
    const html = renderGroup(
      [
        {
          id: "ai-1",
          type: "ai",
          content: "",
          tool_calls: [
            {
              id: "call-1",
              name: "read_file",
              args: { path: "message-group.tsx" },
            },
          ],
        } as Message,
        {
          id: "tool-1",
          type: "tool",
          name: "read_file",
          tool_call_id: "call-1",
          content: "file contents",
        } as Message,
        {
          id: "ai-2",
          type: "ai",
          content: "Zephyr answer body.",
          additional_kwargs: {
            reasoning_content: "The file confirms the renderer order.",
          },
        } as Message,
      ],
      { isLoading: true },
    );

    expectRenderedInOrder(html, [
      "message-group.tsx",
      "Thinking",
      ">Zephyr</span>",
    ]);
  });

  it("keeps assistant text emitted before the trailing reasoning above it", () => {
    const html = renderGroup(
      [
        {
          id: "ai-1",
          type: "ai",
          content: "Quartz interim note.",
        } as Message,
        {
          id: "ai-2",
          type: "ai",
          content: "Zephyr answer body.",
          additional_kwargs: {
            reasoning_content: "Now I can write the final answer.",
          },
        } as Message,
      ],
      { isLoading: true },
    );

    expectRenderedInOrder(html, [
      ">Quartz</span>",
      "Thinking",
      ">Zephyr</span>",
    ]);
  });

  it("keeps tool-calling assistant text visible when reasoning is also present", () => {
    const html = renderGroup([
      {
        id: "ai-1",
        type: "ai",
        content: "I found a likely cause, so I will inspect the renderer next.",
        additional_kwargs: {
          reasoning_content: "Check how processing groups convert messages.",
        },
        tool_calls: [
          {
            id: "call-1",
            name: "bash",
            args: {
              description: "Inspect renderer conversion",
              command: "sed -n '720,780p' message-group.tsx",
            },
          },
        ],
      } as Message,
    ]);

    expect(html).toContain(
      "I found a likely cause, so I will inspect the renderer next.",
    );
    expect(html).toContain("Inspect renderer conversion");
    expect(html).toContain("1 more step");
    expect(html).not.toContain("Check how processing groups convert messages.");
  });

  it("defers browser screenshot previews while the thread is loading", () => {
    const messages = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "call-1",
            name: "browser_navigate",
            args: { url: "https://github.com/bytedance/deer-flow" },
          },
        ],
      } as Message,
      {
        id: "tool-1",
        type: "tool",
        name: "browser_navigate",
        tool_call_id: "call-1",
        content: "Opened",
        additional_kwargs: {
          browser_view: {
            screenshot: "/mnt/user-data/outputs/browser.png",
            url: "https://github.com/bytedance/deer-flow",
          },
        },
      } as Message,
    ];

    const visibleHtml = renderGroup(messages, {
      threadId: "thread-1",
      deferBrowserPreviews: false,
    });
    const deferredHtml = renderGroup(messages, {
      threadId: "thread-1",
      deferBrowserPreviews: true,
    });

    expect(visibleHtml).toContain("<img");
    expect(visibleHtml).toContain('decoding="async"');
    expect(deferredHtml).not.toContain("<img");
  });

  it("keeps the first non-empty result for a tool call and skips task calls", () => {
    const html = renderGroup([
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "call-fetch",
            name: "web_fetch",
            args: { url: "https://example.com" },
          },
          {
            id: "call-task",
            name: "task",
            args: { description: "Do not render this subagent call" },
          },
        ],
      } as Message,
      {
        id: "tool-empty",
        type: "tool",
        name: "web_fetch",
        tool_call_id: "call-fetch",
        content: "",
      } as Message,
      {
        id: "tool-first",
        type: "tool",
        name: "web_fetch",
        tool_call_id: "call-fetch",
        content: "# First fetched title\n\nFirst result.",
      } as Message,
      {
        id: "tool-later",
        type: "tool",
        name: "web_fetch",
        tool_call_id: "call-fetch",
        content: "# Later fetched title\n\nLater result.",
      } as Message,
    ]);

    expect(html).toContain("First fetched title");
    expect(html).not.toContain("Later fetched title");
    expect(html).not.toContain("Do not render this subagent call");
  });

  it("keeps the first browser view that includes a screenshot", () => {
    const html = renderGroup(
      [
        {
          id: "ai-1",
          type: "ai",
          content: "",
          tool_calls: [
            {
              id: "call-browser",
              name: "browser_navigate",
              args: { url: "https://example.com" },
            },
          ],
        } as Message,
        {
          id: "tool-without-shot",
          type: "tool",
          name: "browser_navigate",
          tool_call_id: "call-browser",
          content: "Opened without a preview.",
          additional_kwargs: {
            browser_view: { url: "https://example.com" },
          },
        } as Message,
        {
          id: "tool-first-shot",
          type: "tool",
          name: "browser_navigate",
          tool_call_id: "call-browser",
          content: "Opened with the first preview.",
          additional_kwargs: {
            browser_view: {
              screenshot: "/mnt/user-data/outputs/first-browser.png",
              url: "https://example.com/first",
            },
          },
        } as Message,
        {
          id: "tool-later-shot",
          type: "tool",
          name: "browser_navigate",
          tool_call_id: "call-browser",
          content: "Opened with a later preview.",
          additional_kwargs: {
            browser_view: {
              screenshot: "/mnt/user-data/outputs/later-browser.png",
              url: "https://example.com/later",
            },
          },
        } as Message,
      ],
      { threadId: "thread-1" },
    );

    expect(html).toContain("first-browser.png");
    expect(html).not.toContain("later-browser.png");
    expect(html).toContain("https://example.com/first");
  });

  it("renders the earliest JSON tool result after an empty streamed update", () => {
    const html = renderGroup([
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "call-search",
            name: "web_search",
            args: { query: "DeerFlow" },
          },
        ],
      } as Message,
      {
        id: "tool-empty",
        type: "tool",
        name: "web_search",
        tool_call_id: "call-search",
        content: "",
      } as Message,
      {
        id: "tool-first",
        type: "tool",
        name: "web_search",
        tool_call_id: "call-search",
        content: JSON.stringify([
          { title: "First source", url: "https://first.example" },
        ]),
      } as Message,
      {
        id: "tool-later",
        type: "tool",
        name: "web_search",
        tool_call_id: "call-search",
        content: JSON.stringify([
          { title: "Later source", url: "https://later.example" },
        ]),
      } as Message,
    ]);

    expect(html).toContain("First source");
    expect(html).toContain("https://first.example");
    expect(html).not.toContain("Later source");
    expect(html).not.toContain("https://later.example");
  });
});

describe("scheduler tool steps", () => {
  const actions = [
    ["create", "Scheduled a task", "已创建定时任务"],
    ["update", "Updated a scheduled task", "已修改定时任务"],
    ["list", "Checked scheduled tasks", "查看了定时任务"],
    ["pause", "Paused a scheduled task", "已暂停定时任务"],
    ["resume", "Resumed a scheduled task", "已恢复定时任务"],
    ["delete", "Deleted a scheduled task", "已删除定时任务"],
    ["note", "Saved a note for a scheduled task", "已为定时任务保存备注"],
    ["trial", "Started a trial run", "已开始试运行"],
    ["something-else", "Managed scheduled tasks", "处理了定时任务"],
  ] as const;

  it.each(actions)("labels schedule_task %s in en and zh", (action, en, zh) => {
    expect(
      scheduleToolLabel("schedule_task", { action }, undefined, enUS),
    ).toBe(en);
    expect(
      scheduleToolLabel("schedule_task", { action }, undefined, zhCN),
    ).toBe(zh);
  });

  it("labels a coded error result as a failed change", () => {
    const error = { error: "Ask which timezone", code: "timezone_required" };
    expect(
      scheduleToolLabel("schedule_task", { action: "create" }, error, enUS),
    ).toBe("The scheduled task change didn't go through");
    expect(
      scheduleToolLabel("schedule_task", { action: "create" }, error, zhCN),
    ).toBe("定时任务操作没有成功");
  });

  it("labels a tool-level failure (text, not a JSON result) as failed", () => {
    const text =
      "Error invoking tool 'schedule_task': schedule_type: Input should be 'once', 'interval' or 'cron'";
    expect(
      scheduleToolLabel("schedule_task", { action: "create" }, text, enUS),
    ).toBe("The scheduled task change didn't go through");
    expect(scheduleToolLabel("stop_scheduled_task", {}, text, zhCN)).toBe(
      "定时任务操作没有成功",
    );
    expect(
      scheduleToolLabel(
        "schedule_task",
        { action: "toString" },
        undefined,
        enUS,
      ),
    ).toBe("Managed scheduled tasks");
  });

  it("labels the self-stop and ignores other tools", () => {
    expect(scheduleToolLabel("stop_scheduled_task", {}, undefined, enUS)).toBe(
      "Paused this scheduled task (takes effect when this run ends)",
    );
    expect(scheduleToolLabel("stop_scheduled_task", {}, undefined, zhCN)).toBe(
      "已暂停此定时任务（本次运行结束后生效）",
    );
    expect(scheduleToolLabel("bash", {}, undefined, enUS)).toBeNull();
  });

  it("renders human step labels, never the generic tool label", () => {
    const html =
      renderToolCall(
        "schedule_task",
        { action: "create" },
        JSON.stringify({
          action: "create",
          display: "card",
          task: { id: "task-1" },
        }),
      ) +
      renderToolCall(
        "stop_scheduled_task",
        {},
        JSON.stringify({ action: "stop", stop_requested: true }),
      );
    expect(html).toContain("Scheduled a task");
    expect(html).toContain("Paused this scheduled task");
    expect(html).not.toContain("schedule_task");
    expect(html).not.toContain("stop_scheduled_task");
    expect(html).not.toContain("Use ");
  });
});

// Tool args come from the model and results from search providers, so a
// prompt-injected URL must not become a navigable anchor. React only rewrites
// javascript: hrefs; local and OS-handler schemes would otherwise pass through.
// A blocked URL keeps the markdown path's "Unsafe link omitted" marker.
describe("MessageGroup tool links", () => {
  const unsafeUrls = [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "ms-msdt:/id PCWDiagnostic",
    "vscode://file/etc/passwd",
  ];

  it.each(unsafeUrls)("marks a web_fetch URL of %s as omitted", (url) => {
    const html = renderToolCall("web_fetch", { url });

    expect(html).toContain(`>${url}</span>`);
    expect(html).toContain(`title="Unsafe link scheme in ${url}"`);
    expect(unsafeMarkerCount(html)).toBe(1);
    expect(html).not.toContain("<a");
  });

  it.each(unsafeUrls)("marks a web_search result at %s as omitted", (url) => {
    const html = renderToolCall(
      "web_search",
      { query: "DeerFlow" },
      JSON.stringify([
        { title: "Safe source", url: "https://safe.example" },
        { title: "Injected source", url },
      ]),
    );

    expect(html).toContain('href="https://safe.example"');
    expect(html).toContain(">Injected source</span>");
    expect(unsafeMarkerCount(html)).toBe(1);
    expect(anchorCount(html)).toBe(1);
  });

  it.each(unsafeUrls)(
    "marks an image_search source at %s as omitted",
    (url) => {
      const html = renderToolCall(
        "image_search",
        { query: "DeerFlow" },
        JSON.stringify({
          results: [
            {
              title: "Injected image",
              source_url: url,
              thumbnail_url: "https://images.example/thumb.png",
              image_url: "https://images.example/full.png",
            },
          ],
        }),
      );

      expect(html).toContain('src="https://images.example/thumb.png"');
      expect(unsafeMarkerCount(html)).toBe(1);
      expect(html).not.toContain("<a");
    },
  );

  it("keeps linking web_fetch and image_search results with web URLs", () => {
    const fetchHtml = renderToolCall("web_fetch", {
      url: "https://example.com/page",
    });
    const imageHtml = renderToolCall(
      "image_search",
      { query: "DeerFlow" },
      JSON.stringify({
        results: [
          {
            title: "Image",
            source_url: "https://example.com/source",
            thumbnail_url: "https://images.example/thumb.png",
            image_url: "https://images.example/full.png",
          },
        ],
      }),
    );

    expect(fetchHtml).toContain('href="https://example.com/page"');
    expect(imageHtml).toContain('href="https://example.com/source"');
    expect(unsafeMarkerCount(fetchHtml + imageHtml)).toBe(0);
  });

  // Models occasionally emit non-string args, and the step renders mid-stream;
  // an object reaching the JSX would throw and take down the message list.
  it("renders a web_fetch step whose url arg is not a string", () => {
    const html = renderToolCall("web_fetch", {
      url: { href: "https://example.com/page" },
    });

    expect(html).toContain("View web page");
    expect(html).not.toContain("<a");
  });

  // Persisted or mid-stream tool calls can arrive without an args object;
  // every specialized branch reads args, so none may throw on its absence.
  it.each([
    "web_fetch",
    "web_search",
    "image_search",
    "ls",
    "read_file",
    "write_file",
    "str_replace",
    "bash",
    "ask_clarification",
    "write_todos",
    "schedule_task",
    "stop_scheduled_task",
    "browser_navigate",
    "mcp_lookup",
  ])("renders a %s step whose tool call has no args", (name) => {
    for (const args of [undefined, null]) {
      const render = () =>
        renderGroup([
          {
            id: "ai-1",
            type: "ai",
            content: "",
            tool_calls: [{ id: "call-1", name, args }],
          } as unknown as Message,
        ]);

      expect(render).not.toThrow();
    }
  });
});

function renderToolCall(
  name: string,
  args: Record<string, unknown>,
  content?: string,
) {
  const messages: Message[] = [
    {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [{ id: "call-1", name, args }],
    } as Message,
  ];
  if (content !== undefined) {
    messages.push({
      id: "tool-1",
      type: "tool",
      name,
      tool_call_id: "call-1",
      content,
    } as Message);
  }
  return renderGroup(messages);
}

function unsafeMarkerCount(html: string) {
  return html.split('aria-label="Unsafe link omitted"').length - 1;
}

function anchorCount(html: string) {
  return html.match(/<a\s/g)?.length ?? 0;
}

/** Asserts every needle is present and that they appear in the given order. */
function expectRenderedInOrder(html: string, needles: string[]) {
  const indices = needles.map((needle) => html.indexOf(needle));
  for (const index of indices) {
    expect(index).toBeGreaterThan(-1);
  }
  expect(indices).toStrictEqual([...indices].sort((a, b) => a - b));
}

function renderGroup(
  messages: Message[],
  props: Omit<ComponentProps<typeof MessageGroup>, "messages"> = {},
) {
  return renderToStaticMarkup(
    createElement(
      I18nContext.Provider,
      {
        value: {
          locale: "en-US",
          setLocale: () => undefined,
          t: enUS,
        },
      },
      createElement(MessageGroup, { ...props, messages }),
    ),
  );
}
