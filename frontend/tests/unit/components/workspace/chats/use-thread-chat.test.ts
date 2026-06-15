/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const state = {
    pathname: "/workspace/chats/existing-thread",
    params: { thread_id: "existing-thread" },
    searchParams: new URLSearchParams(),
    uuid: vi.fn<() => string>(),
  };

  return {
    state,
    useParams: vi.fn(() => state.params),
    usePathname: vi.fn(() => state.pathname),
    useSearchParams: vi.fn(() => state.searchParams),
    uuid: state.uuid,
  };
});

vi.mock("next/navigation", () => ({
  useParams: mocks.useParams,
  usePathname: mocks.usePathname,
  useSearchParams: mocks.useSearchParams,
}));

vi.mock("@/core/utils/uuid", () => ({
  uuid: mocks.uuid,
}));

import { useThreadChat } from "@/components/workspace/chats/use-thread-chat";

type Snapshot = {
  threadId: string;
  isNewThread: boolean;
};

type HookValue = {
  threadId: string;
  setThreadId: (value: string) => void;
  isNewThread: boolean;
  setIsNewThread: (value: boolean) => void;
  isMock: boolean;
};

function Probe({
  snapshots,
  onChange,
}: {
  snapshots: Snapshot[];
  onChange?: (value: HookValue) => void;
}) {
  const value = useThreadChat();

  snapshots.push({
    threadId: value.threadId,
    isNewThread: value.isNewThread,
  });
  onChange?.(value);

  return React.createElement("div", {
    "data-thread-id": value.threadId,
    "data-is-new": String(value.isNewThread),
  });
}

describe("useThreadChat", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    mocks.state.pathname = "/workspace/chats/existing-thread";
    mocks.state.params = { thread_id: "existing-thread" };
    mocks.state.searchParams = new URLSearchParams();
    mocks.uuid.mockReset();

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("switches to a fresh new-thread identity without rendering the previous thread first", async () => {
    const snapshots: Snapshot[] = [];

    await React.act(async () => {
      root.render(React.createElement(Probe, { snapshots }));
    });

    expect(snapshots).toEqual([
      { threadId: "existing-thread", isNewThread: false },
    ]);

    mocks.state.pathname = "/workspace/chats/new";
    mocks.state.params = { thread_id: "new" };
    mocks.uuid.mockReturnValueOnce("fresh-thread-id");

    await React.act(async () => {
      root.render(React.createElement(Probe, { snapshots }));
    });

    const afterNavigation = snapshots.slice(1);
    expect(afterNavigation[0]).toEqual({
      threadId: "fresh-thread-id",
      isNewThread: true,
    });
    expect(
      afterNavigation.some((snapshot) => snapshot.threadId === "existing-thread"),
    ).toBe(false);
  });

  it("preserves the created thread after history.replaceState leaves params stale", async () => {
    const snapshots: Snapshot[] = [];
    let latestValue: HookValue | null = null;

    mocks.state.pathname = "/workspace/chats/new";
    mocks.state.params = { thread_id: "new" };
    mocks.uuid.mockReturnValueOnce("draft-thread-id");

    await React.act(async () => {
      root.render(
        React.createElement(Probe, {
          snapshots,
          onChange: (value: HookValue) => {
            latestValue = value;
          },
        }),
      );
    });

    expect(latestValue!.threadId).toBe("draft-thread-id");
    expect(latestValue!.isNewThread).toBe(true);

    await React.act(async () => {
      latestValue?.setThreadId("created-thread-id");
      latestValue?.setIsNewThread(false);
    });

    mocks.state.pathname = "/workspace/chats/created-thread-id";
    mocks.state.params = { thread_id: "new" };

    await React.act(async () => {
      root.render(
        React.createElement(Probe, {
          snapshots,
          onChange: (value: HookValue) => {
            latestValue = value;
          },
        }),
      );
    });

    expect(latestValue!.threadId).toBe("created-thread-id");
    expect(latestValue!.isNewThread).toBe(false);
  });
});
