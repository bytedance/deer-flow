import { afterEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  activatePreferences,
  getBaseSettingsSnapshot,
  updateThreadSettings,
} from "@/core/settings/store";
import type { AgentThread } from "@/core/threads/types";
import { useThreadInputMode } from "@/core/threads/use-thread-input-mode";

afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
});

it("opts one new conversation into Chat and keeps the ordinary account selection", () => {
  const account = activatePreferences(
    { mode: "flash", reasoning_effort: "low" },
    rs.fn(),
  );
  const client = new QueryClient();
  const { result, rerender } = renderHook(
    (id: string) =>
      useThreadInputMode({
        threadId: id,
        isNewThread: true,
        preferred: getBaseSettingsSnapshot().context,
      }),
    {
      initialProps: "first",
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  try {
    expect(result.current.mode).toBe("flash");
    act(() =>
      result.current.changeMode("chat", () =>
        updateThreadSettings("first", "context", {
          mode: "chat",
          reasoning_effort: undefined,
        }),
      ),
    );
    expect(result.current.mode).toBe("chat");
    expect(getBaseSettingsSnapshot().context).toMatchObject({
      mode: "flash",
      reasoning_effort: "low",
    });
    rerender("second");
    expect(result.current.mode).toBe("flash");
  } finally {
    account.stop();
  }
});

it("keeps a saved Chat text-only until the server accepts a mode switch", async () => {
  let finish!: (response: Response) => void;
  const fetcher = rs.fn(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  rs.stubGlobal("fetch", fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity } },
  });
  const thread: AgentThread = {
    thread_id: "t",
    created_at: "",
    updated_at: "",
    status: "idle",
    values: { title: "", messages: [] },
    interrupts: {},
    metadata: { mode: "chat" },
  };
  const key = ["thread", "metadata", "t", false];
  client.setQueryData(key, thread);
  const apply = rs.fn();
  const { result } = renderHook(
    () =>
      useThreadInputMode({
        threadId: "t",
        preferred: { mode: "flash" },
      }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  act(() => result.current.changeMode("flash", apply));
  expect(result.current.mode).toBe("chat");
  expect(result.current.pending).toBe(true);
  expect(apply).not.toHaveBeenCalled();
  await expect(result.current.prepareThread()).rejects.toThrow(
    "thread-mode-changed",
  );
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/t"),
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ metadata: { mode: "flash" } }),
    }),
  );
  await act(async () => {
    finish(
      new Response(
        JSON.stringify({ thread_id: "t", metadata: { mode: "flash" } }),
      ),
    );
  });
  await waitFor(() => expect(result.current.mode).toBe("flash"));
  expect(result.current.pending).toBe(false);
  expect(apply).toHaveBeenCalledTimes(1);
});

it("uses the account's ordinary mode and changes ordinary modes without patching", () => {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity } },
  });
  client.setQueryData(["thread", "metadata", "t", false], {
    metadata: { mode: "flash" },
  });
  const fetcher = rs.fn();
  rs.stubGlobal("fetch", fetcher);
  const apply = rs.fn();
  const { result } = renderHook(
    () =>
      useThreadInputMode({
        threadId: "t",
        preferred: { mode: "pro" },
      }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  expect(result.current.mode).toBe("pro");
  act(() => result.current.changeMode("ultra", apply));
  expect(apply).toHaveBeenCalledOnce();
  expect(fetcher).not.toHaveBeenCalled();
});

it("keeps each thread's pending transition across navigation and drops obsolete account edits", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity } },
  });
  for (const id of ["a", "b"]) {
    client.setQueryData(["thread", "metadata", id, false], {
      thread_id: id,
      metadata: {},
    });
  }
  const responses: Array<(response: Response) => void> = [];
  rs.stubGlobal(
    "fetch",
    () => new Promise<Response>((resolve) => responses.push(resolve)),
  );
  const apply = rs.fn();
  const { result, rerender } = renderHook(
    (id: string) =>
      useThreadInputMode({
        threadId: id,
        preferred: { mode: "pro" },
      }),
    {
      initialProps: "a",
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  act(() => result.current.changeMode("chat", apply));
  rerender("b");
  act(() => result.current.changeMode("chat", apply));
  rerender("a");
  expect(result.current.pending).toBe(true);
  await act(async () => {
    for (const resolve of responses)
      resolve(new Response(JSON.stringify({ metadata: { mode: "chat" } })));
  });
  await waitFor(() => expect(result.current.pending).toBe(false));
  expect(result.current.mode).toBe("chat");
  expect(apply).not.toHaveBeenCalled();
});
