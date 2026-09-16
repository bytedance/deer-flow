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
  useAttachProjectDocument,
  useDeleteProjectDocument,
  useInfiniteProjectDocuments,
  useInfiniteProjectThreadFiles,
  useProjectsConfig,
  usePromoteThreadFile,
  useUploadProjectDocument,
} from "@/core/projects/hooks";

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

test("useInfiniteProjectDocuments pages the shelf under the documents key", async () => {
  const client = makeClient();
  mocks.fetch
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          documents: [DOCUMENT],
          total: 3,
          limit: 100,
          offset: 0,
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          documents: [DOCUMENT, DOCUMENT],
          total: 3,
          limit: 100,
          offset: 1,
        }),
      ),
    );
  const { result, unmount } = renderHook(
    () => useInfiniteProjectDocuments("proj-1"),
    { wrapper: wrapperFor(client) },
  );
  try {
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // total (3) exceeds the loaded count (1): another page exists.
    expect(result.current.hasNextPage).toBe(true);
    const [firstUrl] = mocks.fetch.mock.calls[0] as [string];
    expect(firstUrl).toBe(
      "/backend/api/projects/proj-1/documents?limit=100&offset=0",
    );
    await act(async () => {
      await result.current.fetchNextPage();
    });
    const [nextUrl] = mocks.fetch.mock.calls[1] as [string];
    expect(nextUrl).toBe(
      "/backend/api/projects/proj-1/documents?limit=100&offset=1",
    );
    // All 3 rows are loaded across the two pages: no further page.
    await waitFor(() =>
      expect(
        result.current.data?.pages.flatMap((page) => page.documents),
      ).toHaveLength(3),
    );
    expect(result.current.hasNextPage).toBe(false);
    expect(client.getQueryData(["projects", "documents", "proj-1"])).toEqual(
      result.current.data,
    );
  } finally {
    unmount();
    client.clear();
  }
});

test("useProjectsConfig fetches the server limits under the config key", async () => {
  const client = makeClient();
  const body = { instructions_max_bytes: 16384, trash_retention_days: 7 };
  mocks.fetch.mockResolvedValue(new Response(JSON.stringify(body)));
  const { result, unmount } = renderHook(() => useProjectsConfig(), {
    wrapper: wrapperFor(client),
  });
  try {
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url] = mocks.fetch.mock.calls[0] as [string];
    expect(url).toBe("/backend/api/projects/config");
    expect(client.getQueryData(["projects", "config"])).toEqual(body);
  } finally {
    unmount();
    client.clear();
  }
});

test("useInfiniteProjectThreadFiles pages the conversation-files view under its key", async () => {
  const client = makeClient();
  const body = { groups: [], next_offset: null, truncated: false };
  mocks.fetch.mockResolvedValue(new Response(JSON.stringify(body)));
  const { result, unmount } = renderHook(
    () =>
      useInfiniteProjectThreadFiles("proj-1", {
        thread_limit: 10,
        file_limit: 25,
      }),
    { wrapper: wrapperFor(client) },
  );
  try {
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url] = mocks.fetch.mock.calls[0] as [string];
    expect(url).toBe(
      "/backend/api/projects/proj-1/thread-files?offset=0&thread_limit=10&file_limit=25",
    );
    expect(result.current.hasNextPage).toBe(false);
    expect(
      client.getQueryData([
        "projects",
        "thread-files",
        "proj-1",
        { thread_limit: 10, file_limit: 25 },
      ]),
    ).toEqual(result.current.data);
  } finally {
    unmount();
    client.clear();
  }
});

test("useInfiniteProjectThreadFiles refetches every retained page on invalidation", async () => {
  const client = makeClient();
  const groupA = {
    thread_id: "t-a",
    display_name: "Chat A",
    updated_at: "2026-09-10T00:00:00Z",
    files: [],
    truncated: false,
  };
  const groupB = {
    thread_id: "t-b",
    display_name: "Chat B",
    updated_at: "2026-09-09T00:00:00Z",
    files: [],
    truncated: false,
  };
  const envelope = (groups: (typeof groupA)[], nextOffset: number | null) => ({
    groups,
    next_offset: nextOffset,
    truncated: false,
  });
  mocks.fetch
    .mockResolvedValueOnce(new Response(JSON.stringify(envelope([groupA], 1))))
    .mockResolvedValueOnce(
      new Response(JSON.stringify(envelope([groupB], null))),
    );
  const { result, unmount } = renderHook(
    () => useInfiniteProjectThreadFiles("proj-1"),
    { wrapper: wrapperFor(client) },
  );
  const urls = () => mocks.fetch.mock.calls.map(([url]) => url as string);
  try {
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(result.current.hasNextPage).toBe(false);
    expect(urls()).toEqual([
      "/backend/api/projects/proj-1/thread-files?offset=0",
      "/backend/api/projects/proj-1/thread-files?offset=1",
    ]);

    // t-a is moved out of the project between page loads: the shifted
    // boundary now answers page 1 with groupB and page 2 with nothing.
    mocks.fetch
      .mockResolvedValueOnce(
        new Response(JSON.stringify(envelope([groupB], 1))),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(envelope([], null))));
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ["projects", "thread-files", "proj-1"],
      });
    });
    // BOTH retained pages refetch — never only the current offset.
    await waitFor(() => expect(urls()).toHaveLength(4));
    expect(urls().slice(2)).toEqual([
      "/backend/api/projects/proj-1/thread-files?offset=0",
      "/backend/api/projects/proj-1/thread-files?offset=1",
    ]);
    // The moved-out thread's group is gone, and the shifted boundary did
    // not duplicate the surviving group.
    const groups = result.current.data!.pages.flatMap((page) => page.groups);
    expect(groups.map((group) => group.thread_id)).toEqual(["t-b"]);
  } finally {
    unmount();
    client.clear();
  }
});

test("document queries do not fire in static-demo mode", async () => {
  mocks.isStatic.mockReturnValue(true);
  const client = makeClient();
  const { unmount } = renderHook(
    () => ({
      documents: useInfiniteProjectDocuments("proj-1"),
      threadFiles: useInfiniteProjectThreadFiles("proj-1"),
    }),
    { wrapper: wrapperFor(client) },
  );
  try {
    // Give any (erroneously) enabled query a macrotask to fire.
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

test("useUploadProjectDocument posts multipart and invalidates the projects prefix", async () => {
  const client = makeClient();
  const shelfKey = ["projects", "documents", "proj-1"];
  client.setQueryData(shelfKey, { documents: [], total: 0 });
  mocks.fetch.mockResolvedValue(
    new Response(JSON.stringify({ document: DOCUMENT, deduplicated: false }), {
      status: 201,
    }),
  );
  const { result, unmount } = renderHook(
    () => useUploadProjectDocument("proj-1"),
    { wrapper: wrapperFor(client) },
  );
  try {
    await act(async () => {
      await result.current.mutateAsync({
        file: new File(["hello"], "notes.txt"),
      });
    });
    const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/backend/api/projects/proj-1/documents");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(client.getQueryState(shelfKey)?.isInvalidated).toBe(true);
  } finally {
    unmount();
    client.clear();
  }
});

test("usePromoteThreadFile posts the from-thread body and invalidates projects", async () => {
  const client = makeClient();
  const shelfKey = ["projects", "documents", "proj-1"];
  client.setQueryData(shelfKey, { documents: [], total: 0 });
  mocks.fetch.mockResolvedValue(
    new Response(JSON.stringify({ document: DOCUMENT, deduplicated: false })),
  );
  const { result, unmount } = renderHook(() => usePromoteThreadFile("proj-1"), {
    wrapper: wrapperFor(client),
  });
  try {
    await act(async () => {
      await result.current.mutateAsync({
        thread_id: "thread-1",
        kind: "output",
        name: "report.md",
      });
    });
    const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/backend/api/projects/proj-1/documents/from-thread");
    expect(JSON.parse(init.body as string)).toEqual({
      thread_id: "thread-1",
      kind: "output",
      name: "report.md",
    });
    expect(client.getQueryState(shelfKey)?.isInvalidated).toBe(true);
  } finally {
    unmount();
    client.clear();
  }
});

test("useAttachProjectDocument invalidates projects and threads caches", async () => {
  const client = makeClient();
  const shelfKey = ["projects", "documents", "proj-1"];
  const threadsKey = ["threads", "searchInfinite", {}];
  client.setQueryData(shelfKey, { documents: [], total: 0 });
  client.setQueryData(threadsKey, { pages: [], pageParams: [] });
  mocks.fetch.mockResolvedValue(
    new Response(
      JSON.stringify({
        filename: "q3-report.pdf",
        size_bytes: 1024,
        virtual_path: "/mnt/user-data/uploads/q3-report.pdf",
        artifact_url: "/api/threads/thread-1/artifacts/...",
      }),
    ),
  );
  const { result, unmount } = renderHook(
    () => useAttachProjectDocument("proj-1"),
    { wrapper: wrapperFor(client) },
  );
  try {
    await act(async () => {
      await result.current.mutateAsync({
        documentId: "doc-1",
        threadId: "thread-1",
      });
    });
    const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "/backend/api/projects/proj-1/documents/doc-1/attach-to-thread/thread-1",
    );
    expect(init.method).toBe("POST");
    expect(client.getQueryState(shelfKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(threadsKey)?.isInvalidated).toBe(true);
  } finally {
    unmount();
    client.clear();
  }
});

test("useDeleteProjectDocument deletes and invalidates the projects prefix", async () => {
  const client = makeClient();
  const shelfKey = ["projects", "documents", "proj-1"];
  client.setQueryData(shelfKey, { documents: [], total: 0 });
  mocks.fetch.mockResolvedValue(new Response(null, { status: 204 }));
  const { result, unmount } = renderHook(
    () => useDeleteProjectDocument("proj-1"),
    { wrapper: wrapperFor(client) },
  );
  try {
    await act(async () => {
      await result.current.mutateAsync("doc-1");
    });
    const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/backend/api/projects/proj-1/documents/doc-1");
    expect(init.method).toBe("DELETE");
    expect(client.getQueryState(shelfKey)?.isInvalidated).toBe(true);
  } finally {
    unmount();
    client.clear();
  }
});
