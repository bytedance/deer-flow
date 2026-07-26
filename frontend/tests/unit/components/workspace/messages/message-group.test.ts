import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { MessageGroup } from "@/components/workspace/messages/message-group";
import { I18nContext } from "@/core/i18n/context";

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
        },
      },
      createElement(MessageGroup, { ...props, messages }),
    ),
  );
}
