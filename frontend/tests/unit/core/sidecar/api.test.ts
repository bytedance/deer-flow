import { beforeEach, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://localhost",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import type { SidecarContext } from "@/core/sidecar";
import {
  createSidecarThread,
  findLatestSidecarThread,
} from "@/core/sidecar/api";
import type { AgentThread } from "@/core/threads";

const fetchWithAuth = rs.mocked(fetcher);

beforeEach(() => {
  fetchWithAuth.mockReset();
});

function makeThread(
  threadId: string,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: threadId,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata,
    status: "idle",
    values: { title: threadId, messages: [] },
  } as unknown as AgentThread;
}

function threadResponse(threadId: string): Response {
  return new Response(JSON.stringify(makeThread(threadId)), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const context: SidecarContext = {
  type: "referenced_message",
  label: "Assistant message",
  messageId: "msg-1",
  role: "assistant",
  content: "Answer",
};

test("finds the latest sidecar thread for a parent thread", async () => {
  const sidecar = makeThread("sidecar-1", {
    deerflow_sidecar: true,
    parent_thread_id: "parent-1",
  });
  const search = rs.fn().mockResolvedValue([sidecar]);

  await expect(
    findLatestSidecarThread({
      parentThreadId: "parent-1",
      apiClient: { threads: { search } },
    }),
  ).resolves.toBe(sidecar);

  expect(search).toHaveBeenCalledWith({
    metadata: {
      deerflow_sidecar: true,
      parent_thread_id: "parent-1",
    },
    limit: 1,
    offset: 0,
    sortBy: "updated_at",
    sortOrder: "desc",
  });
});

test("ignores malformed sidecar search results", async () => {
  const search = rs.fn().mockResolvedValue([makeThread("primary-1")]);

  await expect(
    findLatestSidecarThread({
      parentThreadId: "parent-1",
      apiClient: { threads: { search } },
    }),
  ).resolves.toBeNull();
});

test("ignores sidecar search results from another parent thread", async () => {
  const search = rs.fn().mockResolvedValue([
    makeThread("sidecar-1", {
      deerflow_sidecar: true,
      parent_thread_id: "parent-2",
    }),
  ]);

  await expect(
    findLatestSidecarThread({
      parentThreadId: "parent-1",
      apiClient: { threads: { search } },
    }),
  ).resolves.toBeNull();
});

test("coalesces concurrent creates for the same parent into one request", async () => {
  let resolveFetch: ((value: Response) => void) | undefined;
  fetchWithAuth.mockReturnValueOnce(
    new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    }),
  );

  const first = createSidecarThread({ parentThreadId: "parent-1", context });
  const second = createSidecarThread({ parentThreadId: "parent-1", context });

  resolveFetch?.(threadResponse("sidecar-1"));

  const [firstThread, secondThread] = await Promise.all([first, second]);

  expect(fetchWithAuth).toHaveBeenCalledTimes(1);
  expect(firstThread).toEqual(secondThread);
});

test("allows a new create after the in-flight request settles", async () => {
  fetchWithAuth
    .mockResolvedValueOnce(threadResponse("s-1"))
    .mockResolvedValueOnce(threadResponse("s-2"));

  await createSidecarThread({ parentThreadId: "parent-1", context });
  await createSidecarThread({ parentThreadId: "parent-1", context });

  expect(fetchWithAuth).toHaveBeenCalledTimes(2);
});

test("clears the in-flight entry when a create fails", async () => {
  fetchWithAuth
    .mockResolvedValueOnce(new Response(null, { status: 500 }))
    .mockResolvedValueOnce(threadResponse("s-1"));

  await expect(
    createSidecarThread({ parentThreadId: "parent-1", context }),
  ).rejects.toThrow("Failed to create side conversation.");

  await expect(
    createSidecarThread({ parentThreadId: "parent-1", context }),
  ).resolves.toMatchObject({ thread_id: "s-1" });
  expect(fetchWithAuth).toHaveBeenCalledTimes(2);
});
