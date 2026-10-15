import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  clearMemory,
  createMemoryFact,
  deleteMemoryFact,
  importMemory,
  loadMemory,
  updateMemoryFact,
} from "@/core/memory/api";
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
  clearMemory: rs.fn(),
  createMemoryFact: rs.fn(),
  deleteMemoryFact: rs.fn(),
  importMemory: rs.fn(),
  loadMemory: rs.fn(),
  updateMemoryFact: rs.fn(),
}));

const STAMP = "2026-10-15T00:00:00Z";

function memoryDocument(label: string): UserMemory {
  const section = { summary: label, updatedAt: STAMP };
  return {
    version: "1.0",
    lastUpdated: STAMP,
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
    facts: [
      {
        id: "fact-1",
        content: label,
        category: "context",
        confidence: 0.9,
        createdAt: STAMP,
        source: "test",
      },
    ],
  };
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

type MemoryOperation = {
  name: string;
  use: () => {
    isError: boolean;
    mutateAsync: (argument: never) => Promise<unknown>;
  };
  api: () => ReturnType<typeof rs.fn>;
  argument?: unknown;
};

const OPERATIONS: MemoryOperation[] = [
  { name: "clear", use: useClearMemory, api: () => rs.mocked(clearMemory) },
  {
    name: "delete a fact",
    use: useDeleteMemoryFact,
    api: () => rs.mocked(deleteMemoryFact),
    argument: "fact-1",
  },
  {
    name: "import",
    use: useImportMemory,
    api: () => rs.mocked(importMemory),
    argument: memoryDocument("imported"),
  },
  {
    name: "create a fact",
    use: useCreateMemoryFact,
    api: () => rs.mocked(createMemoryFact),
    argument: { content: "new", category: "context", confidence: 0.5 },
  },
  {
    name: "update a fact",
    use: useUpdateMemoryFact,
    api: () => rs.mocked(updateMemoryFact),
    argument: { factId: "fact-1", input: { content: "edited" } },
  },
];

function renderMemoryHooks(use: MemoryOperation["use"]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const view = renderHook(() => ({ memory: useMemory(), operation: use() }), {
    wrapper,
  });
  return { client, view };
}

afterEach(() => {
  cleanup();
  for (const operation of OPERATIONS) {
    operation.api().mockReset();
  }
  rs.mocked(loadMemory).mockReset();
});

describe("memory mutation cache writes", () => {
  for (const operation of OPERATIONS) {
    it(`keeps the confirmed response of "${operation.name}" ahead of a read started before it`, async () => {
      const staleDocument = memoryDocument("before the edit");
      const confirmedDocument = memoryDocument("after the edit");
      const held = deferred<UserMemory>();
      rs.mocked(loadMemory)
        .mockResolvedValueOnce(staleDocument)
        .mockReturnValueOnce(held.promise);
      operation.api().mockResolvedValue(confirmedDocument);

      const { client, view } = renderMemoryHooks(operation.use);
      await waitFor(() =>
        expect(view.result.current.memory.memory).toEqual(staleDocument),
      );

      // A background refetch is in flight with the pre-edit document when the
      // mutation lands.
      void client.refetchQueries({ queryKey: ["memory"] });
      await waitFor(() =>
        expect(rs.mocked(loadMemory)).toHaveBeenCalledTimes(2),
      );

      await view.result.current.operation.mutateAsync(
        operation.argument as never,
      );
      expect(client.getQueryData<UserMemory>(["memory"])).toEqual(
        confirmedDocument,
      );

      held.resolve(staleDocument);
      await waitFor(() => expect(client.isFetching()).toBe(0));
      expect(client.getQueryData<UserMemory>(["memory"])).toEqual(
        confirmedDocument,
      );
    });
  }

  it("still lets a read started after the mutation refresh the cache", async () => {
    const confirmedDocument = memoryDocument("after the edit");
    const refreshedDocument = memoryDocument("later refresh");
    rs.mocked(loadMemory).mockResolvedValue(confirmedDocument);
    rs.mocked(clearMemory).mockResolvedValue(confirmedDocument);

    const { client, view } = renderMemoryHooks(useClearMemory);
    await waitFor(() =>
      expect(view.result.current.memory.memory).toEqual(confirmedDocument),
    );

    await view.result.current.operation.mutateAsync(undefined as never);
    rs.mocked(loadMemory).mockResolvedValueOnce(refreshedDocument);
    await client.refetchQueries({ queryKey: ["memory"] });

    expect(client.getQueryData<UserMemory>(["memory"])).toEqual(
      refreshedDocument,
    );
  });

  it("leaves the cache untouched when the mutation fails", async () => {
    const cachedDocument = memoryDocument("cached");
    rs.mocked(loadMemory).mockResolvedValue(cachedDocument);
    rs.mocked(deleteMemoryFact).mockRejectedValue(new Error("409 conflict"));

    const { client, view } = renderMemoryHooks(useDeleteMemoryFact);
    await waitFor(() =>
      expect(view.result.current.memory.memory).toEqual(cachedDocument),
    );

    await expect(
      view.result.current.operation.mutateAsync("fact-1" as never),
    ).rejects.toThrow("409 conflict");

    expect(client.getQueryData<UserMemory>(["memory"])).toEqual(cachedDocument);
    await waitFor(() =>
      expect(view.result.current.operation.isError).toBe(true),
    );
    expect(client.getQueryData<UserMemory>(["memory"])).toEqual(cachedDocument);
  });
});
