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
import { useEffect, type ReactNode } from "react";

import { ThreadContext } from "@/components/workspace/messages/context";
import {
  SidecarProvider,
  useSidecar,
} from "@/components/workspace/sidecar/context";
import { SidecarPanel } from "@/components/workspace/sidecar/sidecar-panel";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

// PromptInput clears the composer only when onSubmit resolves, so these tests
// drive the real panel and composer and control just the send outcome.

const mocks = rs.hoisted(() => ({
  createSidecarThread: rs.fn(),
  sendMessage: rs.fn(),
  toastError: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

rs.mock("sonner", () => ({
  toast: Object.assign(rs.fn(), { error: mocks.toastError }),
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [],
    tokenUsageEnabled: false,
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: rs.fn(),
  }),
}));

rs.mock("@/core/sidecar/api", () => ({
  createSidecarThread: mocks.createSidecarThread,
  findLatestSidecarThread: async () => null,
}));

rs.mock("@/core/threads/hooks", () => ({
  useDeleteThread: () => ({ mutateAsync: rs.fn(), isPending: false }),
  useThreadStream: () => ({
    thread: { isLoading: false, messages: [], values: {} },
    sendMessage: mocks.sendMessage,
    isUploading: false,
    isHistoryLoading: false,
    hasMoreHistory: false,
    loadMoreHistory: rs.fn(),
  }),
}));

const USER = {
  id: "user-1",
  email: "user@example.test",
  system_role: "user",
  needs_setup: false,
  oauth_provider: null,
} as User;

function Setup({ threadId }: { threadId: string | null }) {
  const sidecar = useSidecar();
  useEffect(() => {
    if (threadId) {
      sidecar.setSidecarThreadId(threadId);
    }
    sidecar.openContext({
      type: "referenced_message",
      label: "Earlier answer",
      role: "assistant",
      content: "Earlier answer",
    });
    // Run once: the setters are stable for the provider's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

function renderPanel(threadId: string | null): ReactNode {
  return (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <AuthProvider initialUser={USER}>
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: false }}
          >
            <SidecarProvider
              parentThreadId="parent-1"
              isMock={false}
              context={{ thread_id: "parent-1" } as never}
            >
              <Setup threadId={threadId} />
              <SidecarPanel />
            </SidecarProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}

async function submitDraft(text: string) {
  const composer = await screen.findByRole<HTMLTextAreaElement>("textbox");
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: text } });
  await act(async () => {
    fireEvent.submit(composer.closest("form")!);
  });
  return composer;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

beforeEach(() => {
  mocks.createSidecarThread.mockReset();
  mocks.sendMessage.mockReset();
  mocks.toastError.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("SidecarPanel keeps the draft when a send fails", () => {
  it("keeps the draft when creating the side chat fails", async () => {
    mocks.createSidecarThread.mockRejectedValue(new Error("create failed"));
    render(renderPanel(null));

    const composer = await submitDraft("my question");
    await waitFor(() =>
      expect(mocks.createSidecarThread).toHaveBeenCalledTimes(1),
    );
    await settle();

    expect(mocks.toastError).toHaveBeenCalledTimes(1);
    expect(mocks.toastError).toHaveBeenCalledWith("create failed");
    expect(mocks.sendMessage).not.toHaveBeenCalled();
    expect(composer.value).toBe("my question");
  });

  it("keeps the draft when sending to an existing side chat fails", async () => {
    mocks.sendMessage.mockRejectedValue(new Error("upload failed"));
    render(renderPanel("sidecar-1"));

    const composer = await submitDraft("my question");
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledTimes(1));
    await settle();

    expect(mocks.toastError).toHaveBeenCalledTimes(1);
    expect(mocks.toastError).toHaveBeenCalledWith("upload failed");
    expect(composer.value).toBe("my question");
  });

  it("keeps the draft when the first send after creating the side chat fails", async () => {
    mocks.createSidecarThread.mockResolvedValue({ thread_id: "sidecar-new" });
    mocks.sendMessage.mockRejectedValue(new Error("upload failed"));
    render(renderPanel(null));

    const composer = await submitDraft("my question");
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledTimes(1));
    expect(mocks.sendMessage.mock.calls[0]?.[0]).toBe("sidecar-new");
    await settle();

    expect(mocks.toastError).toHaveBeenCalledTimes(1);
    expect(mocks.toastError).toHaveBeenCalledWith("upload failed");
    expect(composer.value).toBe("my question");
  });

  it("clears the draft only after the first send to a new side chat finishes", async () => {
    let finishSend!: () => void;
    mocks.createSidecarThread.mockResolvedValue({ thread_id: "sidecar-new" });
    mocks.sendMessage.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishSend = resolve;
        }),
    );
    render(renderPanel(null));

    const composer = await submitDraft("my question");
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledTimes(1));
    await settle();
    expect(composer.value).toBe("my question");

    await act(async () => finishSend());
    await waitFor(() => expect(composer.value).toBe(""));
    expect(mocks.toastError).not.toHaveBeenCalled();
  });
});
