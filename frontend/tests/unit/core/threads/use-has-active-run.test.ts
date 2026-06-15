/* @vitest-environment jsdom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useHasActiveRun } from "@/core/threads/use-has-active-run";
import type { AgentThread } from "@/core/threads/types";

function ActiveRunProbe({
  threadId,
  snapshots,
}: {
  threadId: string | null;
  snapshots: boolean[];
}) {
  const hasActive = useHasActiveRun(threadId);
  snapshots.push(hasActive);
  return React.createElement("div", null, String(hasActive));
}

describe("useHasActiveRun", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    queryClient.clear();
    container.remove();
  });

  function renderProbe(threadId: string | null) {
    const snapshots: boolean[] = [];
    return {
      snapshots,
      render: async () => {
        await React.act(async () => {
          root.render(
            React.createElement(
              QueryClientProvider,
              { client: queryClient },
              React.createElement(ActiveRunProbe, { threadId, snapshots }),
            ),
          );
        });
        await Promise.resolve();
      },
    };
  }

  it("returns false for null threadId", async () => {
    const probe = renderProbe(null);
    await probe.render();
    expect(probe.snapshots.at(-1)).toBe(false);
  });

  it("returns true when thread status is busy", async () => {
    queryClient.setQueryData(["thread", "thread-1"], {
      thread_id: "thread-1",
      status: "busy",
    } satisfies Partial<AgentThread> as AgentThread);

    const probe = renderProbe("thread-1");
    await probe.render();
    expect(probe.snapshots.at(-1)).toBe(true);
  });

  it("returns true when thread status is interrupted", async () => {
    queryClient.setQueryData(["thread", "thread-1"], {
      thread_id: "thread-1",
      status: "interrupted",
    } satisfies Partial<AgentThread> as AgentThread);

    const probe = renderProbe("thread-1");
    await probe.render();
    expect(probe.snapshots.at(-1)).toBe(true);
  });

  it("returns false when thread status is idle", async () => {
    queryClient.setQueryData(["thread", "thread-1"], {
      thread_id: "thread-1",
      status: "idle",
    } satisfies Partial<AgentThread> as AgentThread);

    const probe = renderProbe("thread-1");
    await probe.render();
    expect(probe.snapshots.at(-1)).toBe(false);
  });

  it("returns false when thread not found in cache", async () => {
    const probe = renderProbe("thread-unknown");
    await probe.render();
    expect(probe.snapshots.at(-1)).toBe(false);
  });
});
