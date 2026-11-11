import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { toast } from "sonner";

rs.mock("@/components/workspace/messages/context", () => ({
  useThread: () => ({
    thread: { isLoading: false, messages: [] },
    isMock: false,
  }),
}));
rs.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => ({ setOpen: rs.fn() }),
}));
rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/artifact-save-race",
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: null }),
}));
rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("sonner", () => ({ toast: { success: rs.fn(), error: rs.fn() } }));

// Keep the production content hook, query client and draft providers. Only the
// editor surface is simplified so the test can exercise actual edit/save events.
rs.mock("@/components/workspace/code-editor", () => ({
  CodeEditor: ({
    value,
    readonly,
    disabled,
    onChange,
  }: {
    value: string;
    readonly?: boolean;
    disabled?: boolean;
    onChange?: (value: string) => void;
  }) => (
    <textarea
      aria-label="Artifact source"
      value={value}
      readOnly={readonly}
      disabled={disabled}
      onChange={(event) => onChange?.(event.target.value)}
    />
  ),
}));

import { ArtifactFileDetail } from "@/components/workspace/artifacts/artifact-file-detail";
import { ArtifactsProvider } from "@/components/workspace/artifacts/context";
import { fetch as apiFetch } from "@/core/api/fetcher";
import { ArtifactDraftsProvider } from "@/core/artifacts/draft-context";
import { I18nProvider } from "@/core/i18n/context";

const filepath = "/mnt/user-data/outputs/report.txt";
const threadId = "artifact-save-race";
const oldRevision = "a".repeat(64);
const savedRevision = "b".repeat(64);
const nextRevision = "c".repeat(64);
const mockedFetch = rs.mocked(apiFetch);
let queryClient: QueryClient;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function textResponse(content: string, revision: string) {
  return new Response(content, {
    headers: { ETag: `"${revision}"` },
  });
}

function saveResponse(content: string, revision: string) {
  return new Response(
    JSON.stringify({ path: filepath, sha256: revision, size: content.length }),
    { headers: { "Content-Type": "application/json" } },
  );
}

function Wrapper({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider initialLocale="en-US">
        <ArtifactDraftsProvider>
          <ArtifactsProvider>{children}</ArtifactsProvider>
        </ArtifactDraftsProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

function source() {
  return screen.getByRole<HTMLTextAreaElement>("textbox", {
    name: "Artifact source",
  });
}

beforeEach(() => {
  window.sessionStorage.clear();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  rs.clearAllMocks();
});

describe("artifact saves racing content refetches", () => {
  it.each([
    ["before the save", false, false, false],
    ["during the save", true, false, false],
    ["during a full-file save", true, true, false],
    ["during a save followed by more editing", true, false, true],
  ])(
    "keeps the saved content and revision when a read begun %s finishes late",
    async (
      _scenario,
      refetchDuringSave,
      fullContentRequested,
      editWhileSaving,
    ) => {
      const pendingRead = deferred<Response>();
      const pendingSave = deferred<Response>();
      const savedBodies: unknown[] = [];
      let delayReads = false;

      mockedFetch.mockImplementation(async (_url, options) => {
        if (options?.method === "PUT") {
          savedBodies.push(JSON.parse(options.body as string));
          return savedBodies.length === 1
            ? pendingSave.promise
            : saveResponse("next edit", nextRevision);
        }
        if (delayReads) return pendingRead.promise;
        if (
          fullContentRequested &&
          new Headers(options?.headers).has("Range")
        ) {
          return new Response("old", {
            status: 206,
            headers: {
              ETag: `"${oldRevision}"`,
              "Content-Range": "bytes 0-2/8",
            },
          });
        }
        return textResponse("old file", oldRevision);
      });

      // Restore the provider before mounting the detail, as the real async
      // thread/artifact load does.
      const view = render(<div />, { wrapper: Wrapper });
      view.rerender(
        <ArtifactFileDetail filepath={filepath} threadId={threadId} />,
      );
      if (fullContentRequested) {
        fireEvent.click(
          await screen.findByRole("button", { name: "Load full file" }),
        );
      }
      await waitFor(() => expect(source().value).toBe("old file"));
      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      fireEvent.change(source(), { target: { value: "saved edit" } });

      const queryKey = [
        "artifact",
        filepath,
        threadId,
        false,
        fullContentRequested,
      ];
      let refetch: Promise<void> | undefined;
      const startRead = async () => {
        delayReads = true;
        await act(async () => {
          refetch = queryClient.refetchQueries({ queryKey, exact: true });
        });
        expect(queryClient.isFetching({ queryKey, exact: true })).toBe(1);
      };

      if (!refetchDuringSave) await startRead();
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(savedBodies).toHaveLength(1));
      if (refetchDuringSave) await startRead();

      if (editWhileSaving) {
        // Reopening the panel restores its draft while the original save is
        // still pending, so subsequent typing must survive that completion.
        view.rerender(<div />);
        view.rerender(
          <ArtifactFileDetail filepath={filepath} threadId={threadId} />,
        );
        expect(source().disabled).toBe(false);
        fireEvent.change(source(), { target: { value: "newer draft" } });
      }
      const expectedContent = editWhileSaving ? "newer draft" : "saved edit";
      const unrelatedRead = deferred<string>();
      const unrelatedKeys = [
        [
          "artifact",
          "/mnt/user-data/outputs/other.txt",
          threadId,
          false,
          false,
        ],
        ["artifact", filepath, "other-thread", false, false],
      ];
      const unrelatedQueries = unrelatedKeys.map((key) =>
        queryClient
          .fetchQuery({ queryKey: key, queryFn: () => unrelatedRead.promise })
          .catch(() => null),
      );

      await act(async () => {
        pendingSave.resolve(saveResponse("saved edit", savedRevision));
      });
      await waitFor(() => expect(toast.success).toHaveBeenCalledOnce());
      expect(source().value).toBe(expectedContent);
      for (const key of unrelatedKeys) {
        expect(queryClient.isFetching({ queryKey: key, exact: true })).toBe(1);
      }
      unrelatedRead.resolve("unrelated content");
      expect(await Promise.all(unrelatedQueries)).toEqual([
        "unrelated content",
        "unrelated content",
      ]);

      await act(async () => {
        pendingRead.resolve(textResponse("old file", oldRevision));
        await refetch;
        // Query observer notifications are batched onto the next task.
        await new Promise((resolve) => setTimeout(resolve, 0));
      });

      expect(source().value).toBe(expectedContent);
      expect(screen.queryByText("Changed remotely")).toBeNull();
      expect(queryClient.getQueryData(queryKey)).toMatchObject({
        content: "saved edit",
        sha256: savedRevision,
      });

      // A later edit must compare against the committed revision, otherwise
      // the Gateway rejects it as a false optimistic-concurrency conflict.
      fireEvent.change(source(), { target: { value: "next edit" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(savedBodies).toHaveLength(2));
      expect(savedBodies[1]).toEqual({
        content: "next edit",
        expected_sha256: savedRevision,
      });
      await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(2));
      expect(toast.error).not.toHaveBeenCalled();
    },
  );
});
