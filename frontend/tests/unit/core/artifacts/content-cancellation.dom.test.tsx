import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/components/workspace/messages/context", () => ({
  useThread: () => ({
    thread: { isLoading: false, messages: [] },
    isMock: false,
  }),
}));
rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

import {
  useArtifactContent,
  useStandaloneArtifactContent,
} from "@/core/artifacts/hooks";

const filepath = "/mnt/user-data/outputs/report.txt";
const threadId = "content-cancellation";

function usePanelContent() {
  return useArtifactContent({ filepath, threadId, enabled: true });
}

function useStandaloneContent() {
  return useStandaloneArtifactContent({ filepath, threadId });
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe.each([
  ["panel", usePanelContent],
  ["standalone", useStandaloneContent],
] as const)("%s artifact content cancellation", (_viewer, useContent) => {
  it.each([false, true])(
    "aborts the HTTP request before reading its body (full=%s)",
    async (full) => {
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity } },
      });
      const response = new Response("obsolete file");
      const readBody = rs.spyOn(response, "arrayBuffer");
      const aborted = rs.fn();
      let finishRead!: (response: Response) => void;
      let failRead!: (reason: unknown) => void;
      const pendingRead = new Promise<Response>((resolve, reject) => {
        finishRead = resolve;
        failRead = reject;
      });
      // Model fetch's native abort behavior at the HTTP boundary; the hook,
      // loader and authenticated fetch wrapper all remain production code.
      rs.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
        if (full && new Headers(init?.headers).has("Range")) {
          return new Response("preview", {
            status: 206,
            headers: { "Content-Range": "bytes 0-6/100" },
          });
        }
        init?.signal?.addEventListener(
          "abort",
          () => {
            aborted();
            failRead(new DOMException("Aborted", "AbortError"));
          },
          { once: true },
        );
        return pendingRead;
      });

      function Wrapper({ children }: PropsWithChildren) {
        return (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        );
      }

      const view = renderHook(() => useContent(), { wrapper: Wrapper });
      try {
        if (full) {
          await waitFor(() => expect(view.result.current.truncated).toBe(true));
          act(() => view.result.current.loadFullContent());
        }
        await waitFor(() =>
          expect(globalThis.fetch).toHaveBeenCalledTimes(full ? 2 : 1),
        );

        await act(async () => {
          await client.cancelQueries({
            queryKey: ["artifact", filepath, threadId, false],
          });
        });

        expect(aborted).toHaveBeenCalledOnce();
        expect(readBody).not.toHaveBeenCalled();
        expect(view.result.current.error).toBeNull();
        expect(client.isFetching()).toBe(0);
      } finally {
        finishRead(response);
        view.unmount();
        client.clear();
      }
    },
  );
});
