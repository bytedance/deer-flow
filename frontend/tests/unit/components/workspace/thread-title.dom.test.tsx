import type { BaseStream } from "@langchain/langgraph-sdk";
import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";

import { ThreadTitle } from "@/components/workspace/thread-title";
import type { AgentThreadState } from "@/core/threads";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      pages: {
        appName: "DeerFlow",
        newChat: "New chat",
        untitled: "Untitled",
      },
    },
  }),
}));

rs.mock("@/components/workspace/chats", () => ({
  useThreadChat: () => ({ isNewThread: false }),
}));

rs.mock("@/components/workspace/flip-display", () => ({
  FlipDisplay: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

function makeThread(title: string): BaseStream<AgentThreadState> {
  return {
    isThreadLoading: false,
    values: { title },
  } as unknown as BaseStream<AgentThreadState>;
}

afterEach(() => {
  cleanup();
  document.title = "";
});

test("prefers the canonical metadata title over a stale stream title", () => {
  const { container } = render(
    <ThreadTitle
      threadId="thread-1"
      thread={makeThread("Stream title")}
      canonicalTitle="Renamed title"
    />,
  );

  expect(container.textContent).toBe("Renamed title");
  expect(document.title).toBe("Renamed title - DeerFlow");
});

test("falls back to the stream title when metadata is unavailable", () => {
  const { container } = render(
    <ThreadTitle threadId="thread-1" thread={makeThread("Stream title")} />,
  );

  expect(container.textContent).toBe("Stream title");
  expect(document.title).toBe("Stream title - DeerFlow");
});

test("falls back to the stream title when metadata title is empty", () => {
  const { container } = render(
    <ThreadTitle
      threadId="thread-1"
      thread={makeThread("Stream title")}
      canonicalTitle=""
    />,
  );

  expect(container.textContent).toBe("Stream title");
  expect(document.title).toBe("Stream title - DeerFlow");
});
