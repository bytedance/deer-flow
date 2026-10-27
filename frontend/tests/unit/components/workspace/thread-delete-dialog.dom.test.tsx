import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
} from "@tanstack/react-query";
import {
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
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

const { deleteThread } = rs.hoisted(() => ({ deleteThread: rs.fn() }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace: rs.fn() }),
  usePathname: () => "/workspace/chats/new",
  useParams: () => ({}),
}));
rs.mock("sonner", () => ({ toast: { error: rs.fn() } }));
rs.mock("@/components/workspace/chats/use-thread-chat", () => ({
  resetThreadChatAfterDelete: rs.fn(),
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
