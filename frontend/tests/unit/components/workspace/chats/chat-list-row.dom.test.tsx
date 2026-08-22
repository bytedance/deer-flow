import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { ChatListRow } from "@/components/workspace/chats/chat-list-row";
import type { AgentThread } from "@/core/threads/types";
import { THREAD_PINNED_METADATA_KEY } from "@/core/threads/utils";

const THREAD_ID = "00000000-0000-0000-0000-000000000901";

const mocks = rs.hoisted(() => ({
  staticWebsiteOnly: "false",
  imeComposing: false,
  pinMutate: rs.fn(),
  renameMutate: rs.fn(),
  deleteMutate: rs.fn(),
  deletePending: false,
  toastError: rs.fn(),
  resetThreadChatAfterDelete: rs.fn(),
}));

rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
    ...props
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className} {...props}>
      {children}
    </a>
  ),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      common: {
        delete: "Delete",
        rename: "Rename",
        cancel: "Cancel",
        save: "Save",
        renameFailed: "Failed to rename thread.",
      },
      chats: {
        pinChat: "Pin chat",
        unpinChat: "Unpin chat",
        pinChatFailed: "Failed to update pinned chat",
        mainChat: "Main chat",
        pinnedBadge: "Pinned",
        deleteConfirm:
          "Delete this conversation? This cannot be undone and will remove its chat history.",
        deleteFailed: "Failed to delete conversation.",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: false }),
  useAgents: () => ({ agents: [] }),
}));

rs.mock("@/core/threads/hooks", () => ({
  usePinThread: () => ({ mutate: mocks.pinMutate }),
  useRenameThread: () => ({ mutate: mocks.renameMutate }),
  useDeleteThread: () => ({
    mutate: mocks.deleteMutate,
    isPending: mocks.deletePending,
  }),
}));

rs.mock("@/env", () => ({
  env: {
    get NEXT_PUBLIC_STATIC_WEBSITE_ONLY() {
      return mocks.staticWebsiteOnly;
    },
  },
}));

rs.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
  },
}));

rs.mock("@/components/workspace/chats/use-thread-chat", () => ({
  resetThreadChatAfterDelete: mocks.resetThreadChatAfterDelete,
}));

rs.mock("@/lib/ime", () => ({
  isIMEComposing: () => mocks.imeComposing,
}));

function makeThread(overrides?: Partial<AgentThread>): AgentThread {
  return {
    thread_id: THREAD_ID,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T12:00:00Z",
    metadata: {},
    values: {
      title: "My chat",
      messages: [],
    },
    ...overrides,
  } as AgentThread;
}

function openDeleteConfirm() {
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  return screen.getByRole("dialog");
}

function openRenameDialog() {
  fireEvent.click(screen.getByRole("button", { name: "Rename" }));
  return screen.getByRole("dialog");
}

afterEach(() => {
  mocks.staticWebsiteOnly = "false";
  mocks.imeComposing = false;
  mocks.deletePending = false;
  mocks.pinMutate.mockReset();
  mocks.renameMutate.mockReset();
  mocks.deleteMutate.mockReset();
  mocks.toastError.mockReset();
  mocks.resetThreadChatAfterDelete.mockReset();
  cleanup();
});

describe("ChatListRow mutations", () => {
  it("pins an unpinned thread with the expected mutation args", () => {
    render(<ChatListRow thread={makeThread()} selected={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Pin chat" }));

    expect(mocks.pinMutate).toHaveBeenCalledWith(
      { threadId: THREAD_ID, pinned: true },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it("unpins a pinned thread with the expected mutation args", () => {
    render(
      <ChatListRow
        thread={makeThread({
          metadata: { [THREAD_PINNED_METADATA_KEY]: true },
        })}
        selected={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Unpin chat" }));

    expect(mocks.pinMutate).toHaveBeenCalledWith(
      { threadId: THREAD_ID, pinned: false },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it("shows a toast when pin mutation fails", () => {
    mocks.pinMutate.mockImplementation((_args, { onError }) => {
      onError(new Error("pin failed"));
    });

    render(<ChatListRow thread={makeThread()} selected={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Pin chat" }));

    expect(mocks.toastError).toHaveBeenCalledWith("pin failed");
  });

  it("confirms delete with thread id and selected-thread cleanup hook", () => {
    mocks.deleteMutate.mockImplementation((_args, { onSuccess }) => {
      onSuccess();
    });

    render(<ChatListRow thread={makeThread()} selected />);

    const dialog = openDeleteConfirm();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(mocks.deleteMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        threadId: THREAD_ID,
        onRemoteDeleted: expect.any(Function),
      }),
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );

    const [{ onRemoteDeleted }] = mocks.deleteMutate.mock.calls[0] as [
      { onRemoteDeleted?: () => void },
      unknown,
    ];
    onRemoteDeleted?.();
    expect(mocks.resetThreadChatAfterDelete).toHaveBeenCalledWith({
      deletedThreadId: THREAD_ID,
      nextPath: "/workspace/chats",
      force: true,
    });
  });

  it("omits onRemoteDeleted when the row is not selected", () => {
    render(<ChatListRow thread={makeThread()} selected={false} />);

    const dialog = openDeleteConfirm();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(mocks.deleteMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        threadId: THREAD_ID,
        onRemoteDeleted: undefined,
      }),
      expect.any(Object),
    );
  });

  it("keeps the delete dialog open and toasts when delete fails", () => {
    mocks.deleteMutate.mockImplementation((_args, { onError }) => {
      onError(new Error("delete failed"));
    });

    render(<ChatListRow thread={makeThread()} selected={false} />);

    const dialog = openDeleteConfirm();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(mocks.toastError).toHaveBeenCalledWith("delete failed");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("does not rename when the trimmed title is empty", () => {
    render(<ChatListRow thread={makeThread()} selected={false} />);

    const dialog = openRenameDialog();
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "   " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(mocks.renameMutate).not.toHaveBeenCalled();
  });

  it("submits rename with trimmed title", () => {
    mocks.renameMutate.mockImplementation((_args, { onSuccess }) => {
      onSuccess();
    });

    render(<ChatListRow thread={makeThread()} selected={false} />);

    const dialog = openRenameDialog();
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "  Renamed chat  " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(mocks.renameMutate).toHaveBeenCalledWith(
      { threadId: THREAD_ID, title: "Renamed chat" },
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
  });

  it("does not submit rename on Enter while IME is composing", () => {
    mocks.imeComposing = true;

    render(<ChatListRow thread={makeThread()} selected={false} />);

    const dialog = openRenameDialog();
    const input = within(dialog).getByRole("textbox");
    fireEvent.change(input, { target: { value: "Renamed chat" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(mocks.renameMutate).not.toHaveBeenCalled();
  });
});

describe("ChatListRow static website mode", () => {
  it("hides pin, rename, and delete actions", () => {
    mocks.staticWebsiteOnly = "true";

    render(<ChatListRow thread={makeThread()} selected={false} />);

    expect(screen.queryByRole("button", { name: "Pin chat" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});
