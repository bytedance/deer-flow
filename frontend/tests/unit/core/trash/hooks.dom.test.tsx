import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  isStatic: rs.fn(() => false),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: mocks.isStatic,
}));

import {
  useEmptyTrash,
  useInfiniteTrashDocuments,
  usePurgeDocument,
  useRestoreDocument,
} from "@/core/trash/hooks";

const DOCUMENT = {
  id: "doc-1",
  name: "q3-report.pdf",
  size_bytes: 1024,
  sha256: "abc123",
  content_missing: false,
  source_thread_id: null,
  source_kind: null,
  source_name: null,
  created_at: "2026-09-10T00:00:00+00:00",
  updated_at: "2026-09-10T00:00:00+00:00",
};

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapperFor(client: QueryClient) {
  return function QueryWrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

afterEach(() => {
  cleanup();
  rs.resetAllMocks();
  mocks.isStatic.mockReturnValue(false);
});

test("useInfiniteTrashDocuments pages the trash list under the trash key", async () => {
  const client = makeClient();
  const trashed = {
    ...DOCUMENT,
    trashed_at: "2026-09-12T00:00:00+00:00",
    trash_origin: null,
  };
  mocks.fetch
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          documents: [trashed],
          total: 2,
          limit: 100,
          offset: 0,
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          documents: [trashed],
          total: 2,
          limit: 100,
          offset: 1,
        }),
      ),
    );
  const { result, unmount } = renderHook(() => useInfiniteTrashDocuments(), {
    wrapper: wrapperFor(client),
  });
  try {
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    const [firstUrl] = mocks.fetch.mock.calls[0] as [string];
    expect(firstUrl).toBe("/backend/api/trash/documents?limit=100&offset=0");
    await act(async () => {
      await result.current.fetchNextPage();
    });
    const [nextUrl] = mocks.fetch.mock.calls[1] as [string];
    expect(nextUrl).toBe("/backend/api/trash/documents?limit=100&offset=1");
    await waitFor(() =>
      expect(
        result.current.data?.pages.flatMap((page) => page.documents),
      ).toHaveLength(2),
    );
    expect(result.current.hasNextPage).toBe(false);
    expect(client.getQueryData(["trash", "documents"])).toEqual(
      result.current.data,
    );
  } finally {
    unmount();
    client.clear();
  }
});

test("useInfiniteTrashDocuments does not fire in static-demo mode", async () => {
  mocks.isStatic.mockReturnValue(true);
  const client = makeClient();
  const { unmount } = renderHook(() => useInfiniteTrashDocuments(), {
    wrapper: wrapperFor(client),
  });
  try {
    await act(async () => {
      // ES2022 lib has no Promise.withResolvers typing; executor form required.
      await new Promise<void>((resolve) => setTimeout(() => resolve(), 20));
    });
    expect(mocks.fetch).not.toHaveBeenCalled();
  } finally {
    unmount();
    client.clear();
  }
});

test("useRestoreDocument posts and invalidates trash and projects caches", async () => {
  const client = makeClient();
  const trashKey = ["trash", "documents"];
  const projectsKey = ["projects", "documents", "proj-1"];
  client.setQueryData(trashKey, { documents: [], total: 0 });
  client.setQueryData(projectsKey, { documents: [], total: 0 });
  mocks.fetch.mockResolvedValue(
    new Response(JSON.stringify({ outcome: "restored", document: DOCUMENT })),
  );
  const { result, unmount } = renderHook(() => useRestoreDocument(), {
    wrapper: wrapperFor(client),
  });
  try {
    await act(async () => {
      await result.current.mutateAsync({ documentId: "doc-1" });
    });
    const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/backend/api/trash/documents/doc-1/restore");
    expect(init.method).toBe("POST");
    expect(client.getQueryState(trashKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(projectsKey)?.isInvalidated).toBe(true);
  } finally {
    unmount();
    client.clear();
  }
});

test("usePurgeDocument posts and invalidates trash and projects caches", async () => {
  const client = makeClient();
  const trashKey = ["trash", "documents"];
  const projectsKey = ["projects", "documents", "proj-1"];
  client.setQueryData(trashKey, { documents: [], total: 0 });
  client.setQueryData(projectsKey, { documents: [], total: 0 });
  mocks.fetch.mockResolvedValue(new Response(null, { status: 204 }));
  const { result, unmount } = renderHook(() => usePurgeDocument(), {
    wrapper: wrapperFor(client),
  });
  try {
    await act(async () => {
      await result.current.mutateAsync("doc-1");
    });
    const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/backend/api/trash/documents/doc-1/purge");
    expect(init.method).toBe("POST");
    expect(client.getQueryState(trashKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(projectsKey)?.isInvalidated).toBe(true);
  } finally {
    unmount();
    client.clear();
  }
});

test("useEmptyTrash posts and invalidates only the trash cache", async () => {
  const client = makeClient();
  const trashKey = ["trash", "documents"];
  const projectsKey = ["projects", "documents", "proj-1"];
  client.setQueryData(trashKey, { documents: [], total: 0 });
  client.setQueryData(projectsKey, { documents: [], total: 0 });
  mocks.fetch.mockResolvedValue(new Response(JSON.stringify({ purged: 2 })));
  const { result, unmount } = renderHook(() => useEmptyTrash(), {
    wrapper: wrapperFor(client),
  });
  try {
    await act(async () => {
      await result.current.mutateAsync();
    });
    const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/backend/api/trash/purge");
    expect(init.method).toBe("POST");
    expect(client.getQueryState(trashKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(projectsKey)?.isInvalidated).toBe(false);
  } finally {
    unmount();
    client.clear();
  }
});
