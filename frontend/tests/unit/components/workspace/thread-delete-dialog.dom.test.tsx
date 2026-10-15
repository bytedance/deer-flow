import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
} from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { toast } from "sonner";

import {
  ThreadDeleteDialogProvider,
  useThreadDeleteDialog,
} from "@/components/workspace/thread-delete-dialog";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import {
  WorkspaceProvider,
  WorkspaceReadyBoundary,
  useWorkspaceContext,
  type WorkspaceContextValue,
} from "@/core/workspaces/context";

const { deleteThread, replace, resetThread } = rs.hoisted(() => ({
  deleteThread: rs.fn(),
  replace: rs.fn(),
  resetThread: rs.fn(),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/workspace/chats/new",
  useParams: () => ({ thread_id: "thread-1" }),
}));
rs.mock("sonner", () => ({ toast: { error: rs.fn() } }));
rs.mock("@/components/workspace/chats/use-thread-chat", () => ({
  resetThreadChatAfterDelete: resetThread,
}));
rs.mock("@/core/threads/hooks", () => ({
  useDeleteThread: () => useMutation({ mutationFn: deleteThread }),
}));

function Trigger() {
  const requestDelete = useThreadDeleteDialog();
  return (
    <button
      onClick={() =>
        requestDelete({
          thread: {
            thread_id: "thread-1",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            metadata: {},
            status: "idle",
            values: { title: "Keep me", messages: [] },
            interrupts: {},
          },
        })
      }
    >
      Open deletion
    </button>
  );
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.unstubAllGlobals();
  rs.clearAllMocks();
});

describe("thread deletion failure feedback", () => {
  for (const [name, error, message] of [
    ["specific error", new Error("Permission denied"), "Permission denied"],
    ["empty error", new Error(""), "Failed to delete chat. Please try again."],
    ["non-Error rejection", null, "Failed to delete chat. Please try again."],
  ] as const) {
    it(`reports ${name} and restores Cancel focus`, async () => {
      deleteThread.mockRejectedValueOnce(error);
      const log = rs
        .spyOn(console, "error")
        .mockImplementation(() => undefined);
      const client = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      render(
        <I18nProvider initialLocale={DEFAULT_LOCALE}>
          <QueryClientProvider client={client}>
            <ThreadDeleteDialogProvider>
              <Trigger />
            </ThreadDeleteDialogProvider>
          </QueryClientProvider>
        </I18nProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Open deletion" }));
      const cancel = await screen.findByRole("button", {
        name: "Cancel",
      });
      const del = screen.getByRole("button", { name: "Delete" });
      del.focus();
      fireEvent.click(del);
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
      await waitFor(() => expect(document.activeElement).toBe(cancel));
      expect(log).toHaveBeenCalledWith("Failed to delete chat:", error);
      expect(screen.getByRole("dialog")).not.toBeNull();
      fireEvent.click(cancel);
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      client.clear();
    });
  }
});

it("ignores old delete completion callbacks and failure toasts after a real workspace switch", async () => {
  const P = "11111111-1111-1111-1111-111111111111";
  const T = "22222222-2222-2222-2222-222222222222";
  rs.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        window.location.href,
      ).pathname;
      if (path === "/api/workspaces")
        return Response.json(
          [P, T].map((id) => ({
            id,
            name: id,
            kind: id === P ? "personal" : "team",
            personal_user_id: id === P ? "alice" : null,
            status: "active",
            role: "owner",
            membership_version: 1,
            policy_version: 1,
          })),
        );
      if (path === "/api/workspaces/current")
        return Response.json({
          actor_user_id: "alice",
          workspace_id: new Headers(init?.headers).get("X-Deerflow-Workspace"),
          membership_version: 1,
          policy_version: 1,
        });
      throw new Error(`Unexpected delete dialog request ${path}`);
    },
  );
  let context: WorkspaceContextValue | null = null;
  function Controls() {
    context = useWorkspaceContext();
    return null;
  }
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  deleteThread.mockImplementationOnce(
    async ({ onDeleted }: { onDeleted?: () => void }) => {
      await gate;
      onDeleted?.();
      throw new Error("Old workspace failure");
    },
  );
  const log = rs.spyOn(console, "error").mockImplementation(() => undefined);
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  render(
    <AuthProvider
      initialUser={{
        id: "alice",
        email: "alice@example.test",
        system_role: "user",
        needs_setup: false,
      }}
    >
      <I18nProvider initialLocale={DEFAULT_LOCALE}>
        <QueryClientProvider client={client}>
          <WorkspaceProvider enabled>
            <Controls />
            <WorkspaceReadyBoundary>
              <ThreadDeleteDialogProvider>
                <Trigger />
              </ThreadDeleteDialogProvider>
            </WorkspaceReadyBoundary>
          </WorkspaceProvider>
        </QueryClientProvider>
      </I18nProvider>
    </AuthProvider>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Open deletion" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  await waitFor(() => expect(deleteThread).toHaveBeenCalledTimes(1));
  await act(async () => {
    expect(await context!.select(T)).toBe(true);
  });
  await screen.findByRole("button", { name: "Open deletion" });
  await act(async () => {
    release();
    await gate;
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(replace).not.toHaveBeenCalled();
  expect(resetThread).not.toHaveBeenCalled();
  expect(toast.error).not.toHaveBeenCalled();
  expect(log).not.toHaveBeenCalled();
  client.clear();
});
