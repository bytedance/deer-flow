import { afterEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import * as api from "@/core/memory/api";
import {
  useClearMemory,
  useCreateMemoryFact,
  useDeleteMemoryFact,
  useImportMemory,
  useMemory,
  useUpdateMemoryFact,
} from "@/core/memory/hooks";
import type { UserMemory } from "@/core/memory/types";

rs.mock("@/core/memory/api", () => ({
  loadMemory: rs.fn(),
  clearMemory: rs.fn(),
  createMemoryFact: rs.fn(),
  deleteMemoryFact: rs.fn(),
  importMemory: rs.fn(),
  updateMemoryFact: rs.fn(),
}));

function memory(contents: string[], revision: number): UserMemory {
  const section = { summary: "", updatedAt: "" };
  return {
    version: "1.0",
    revision,
    lastUpdated: "2026-10-15T10:00:00Z",
    user: {
      workContext: section,
      personalContext: section,
      topOfMind: section,
      cognitiveStyle: section,
    },
    history: {
      recentMonths: section,
      earlierContext: section,
      longTermBackground: section,
    },
    facts: contents.map((content) => ({
      id: content,
      content,
      category: "context",
      confidence: 0.8,
      createdAt: "2026-10-15T10:00:00Z",
      source: "manual",
    })),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  rs.resetAllMocks();
});

const cases = [
  { action: "clear", contents: [] },
  { action: "delete", contents: [] },
  { action: "import", contents: ["imported fact"] },
  { action: "create", contents: ["old fact", "new fact"] },
  { action: "update", contents: ["edited fact"] },
] as const;

for (const { action, contents } of cases) {
  test(`a delayed memory read cannot overwrite a confirmed ${action}`, async () => {
    const before = memory(["old fact"], 1);
    const confirmed = memory([...contents], 2);
    const delayedRead = deferred<UserMemory>();
    rs.mocked(api.loadMemory)
      .mockResolvedValueOnce(before)
      .mockReturnValueOnce(delayedRead.promise);
    rs.mocked(api.clearMemory).mockResolvedValue(confirmed);
    rs.mocked(api.deleteMemoryFact).mockResolvedValue(confirmed);
    rs.mocked(api.importMemory).mockResolvedValue(confirmed);
    rs.mocked(api.createMemoryFact).mockResolvedValue(confirmed);
    rs.mocked(api.updateMemoryFact).mockResolvedValue(confirmed);

    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: Infinity },
        mutations: { retry: false, gcTime: Infinity },
      },
    });
    clients.push(client);
    function wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    }
    const { result } = renderHook(
      () => ({
        query: useMemory(),
        clear: useClearMemory(),
        delete: useDeleteMemoryFact(),
        import: useImportMemory(),
        create: useCreateMemoryFact(),
        update: useUpdateMemoryFact(),
      }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.query.memory).toEqual(before));

    // Model a focus/refetch GET that captured the old server snapshot before
    // the user mutated memory, but whose response is delayed in transit.
    let refetch!: Promise<void>;
    act(() => {
      refetch = client.refetchQueries({ queryKey: ["memory"] });
    });
    expect(api.loadMemory).toHaveBeenCalledTimes(2);

    await act(async () => {
      switch (action) {
        case "clear":
          await result.current.clear.mutateAsync();
          break;
        case "delete":
          await result.current.delete.mutateAsync("old fact");
          break;
        case "import":
          await result.current.import.mutateAsync(confirmed);
          break;
        case "create":
          await result.current.create.mutateAsync({
            content: "new fact",
            category: "context",
            confidence: 0.8,
          });
          break;
        case "update":
          await result.current.update.mutateAsync({
            factId: "old fact",
            input: { content: "edited fact" },
          });
          break;
      }
    });
    expect(client.getQueryData(["memory"])).toEqual(confirmed);

    await act(async () => {
      delayedRead.resolve(before);
      await refetch;
    });
    expect(client.getQueryData(["memory"])).toEqual(confirmed);
    await waitFor(() => expect(result.current.query.memory).toEqual(confirmed));

    // Cancelling the older read must not prevent subsequent server refreshes.
    const refreshed = memory(["newer server fact"], 3);
    rs.mocked(api.loadMemory).mockResolvedValueOnce(refreshed);
    await act(async () => {
      await client.refetchQueries({ queryKey: ["memory"] });
    });
    await waitFor(() => expect(result.current.query.memory).toEqual(refreshed));
  });
}

test("a failed clear preserves the cache and allows an in-flight read to finish", async () => {
  const before = memory(["old fact"], 1);
  const refreshed = memory(["newer server fact"], 2);
  const delayedRead = deferred<UserMemory>();
  rs.mocked(api.loadMemory).mockReturnValue(delayedRead.promise);
  rs.mocked(api.clearMemory).mockRejectedValue(new Error("Clear failed"));
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  clients.push(client);
  client.setQueryData(["memory"], before);
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }
  const { result } = renderHook(
    () => ({ query: useMemory(), clear: useClearMemory() }),
    { wrapper },
  );
  await waitFor(() => expect(api.loadMemory).toHaveBeenCalledTimes(1));

  await act(async () => {
    await expect(result.current.clear.mutateAsync()).rejects.toThrow(
      "Clear failed",
    );
  });
  expect(client.getQueryData(["memory"])).toEqual(before);

  await act(async () => {
    delayedRead.resolve(refreshed);
  });
  await waitFor(() => expect(result.current.query.memory).toEqual(refreshed));
});
