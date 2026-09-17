import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { stageProjectAttachment } from "@/core/projects/composer-attach";
import type { AttachProjectDocumentResult } from "@/core/projects/types";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

// The composer's model selector is irrelevant to submit gating; keep the
// react-query + network machinery out of the way entirely.
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

const ATTACHMENT: AttachProjectDocumentResult = {
  filename: "roadmap.md",
  size_bytes: 2048,
  virtual_path: "/mnt/user-data/uploads/roadmap.md",
  artifact_url:
    "/api/threads/thread-1/artifacts/mnt/user-data/uploads/roadmap.md",
};

const STAGED_FILE = {
  filename: "roadmap.md",
  size: 2048,
  path: "/mnt/user-data/uploads/roadmap.md",
  status: "uploaded",
};

const OTHER_ATTACHMENT: AttachProjectDocumentResult = {
  filename: "notes.txt",
  size_bytes: 128,
  virtual_path: "/mnt/user-data/uploads/notes.txt",
  artifact_url:
    "/api/threads/thread-1/artifacts/mnt/user-data/uploads/notes.txt",
};

const OTHER_STAGED_FILE = {
  filename: "notes.txt",
  size: 128,
  path: "/mnt/user-data/uploads/notes.txt",
  status: "uploaded",
};

type SubmitSpy = ReturnType<typeof rs.fn>;

function renderComposer({ onSubmit }: { onSubmit: SubmitSpy }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const tree = (onSubmitProp: SubmitSpy): ReactNode => (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider
          initialUser={{
            id: "user-1",
            email: "user@example.test",
            system_role: "user",
            needs_setup: false,
            oauth_provider: null,
          }}
        >
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: true }}
          >
            <PromptInputProvider>
              <InputBox
                threadId="thread-1"
                status="ready"
                context={{ mode: "flash" } as never}
                onSubmit={onSubmitProp}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
  return render(tree(onSubmit));
}

function getSubmitButton(container: HTMLElement): HTMLButtonElement {
  const button = container.querySelector('button[type="submit"]');
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("submit button not rendered");
  }
  return button;
}

function lastSubmit(onSubmit: SubmitSpy): {
  message: PromptInputMessage;
  options: InputBoxSubmitOptions | undefined;
} {
  const [message, options] = onSubmit.mock.calls.at(-1) as [
    PromptInputMessage,
    InputBoxSubmitOptions?,
  ];
  return { message, options };
}

afterEach(() => {
  rs.restoreAllMocks();
  cleanup();
  window.sessionStorage.clear();
});

describe("InputBox staged project attachments", () => {
  it("submits an attachment-only message instead of reading it as empty", async () => {
    stageProjectAttachment("thread-1", ATTACHMENT);
    const onSubmit = rs.fn();
    const { container } = renderComposer({ onSubmit });

    // The staged chip is applied from session storage on mount.
    await screen.findByTestId("project-attachment-chip");
    fireEvent.click(getSubmitButton(container));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const { message, options } = lastSubmit(onSubmit);
    expect(message.text).toBe("");
    expect(options?.additionalKwargs?.files).toEqual([STAGED_FILE]);
  });

  it("does not intercept /goal while an attach chip is present", async () => {
    stageProjectAttachment("thread-1", ATTACHMENT);
    const onSubmit = rs.fn();
    const { container } = renderComposer({ onSubmit });

    await screen.findByTestId("project-attachment-chip");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "/goal check this" },
    });
    fireEvent.click(getSubmitButton(container));

    // The line goes out as an ordinary message WITH the attachment — the
    // goal interception would have stripped the "/goal " prefix and dropped
    // the staged files.
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const { message, options } = lastSubmit(onSubmit);
    expect(message.text).toBe("/goal check this");
    expect(options?.additionalKwargs?.files).toEqual([STAGED_FILE]);
  });

  it("keeps plain text-only and truly-empty submit behavior unchanged", async () => {
    const onSubmit = rs.fn();
    const { container } = renderComposer({ onSubmit });

    // No staged attachment, empty text: nothing is submitted.
    fireEvent.click(getSubmitButton(container));
    await waitFor(() =>
      expect(screen.queryByTestId("project-attachment-chip")).toBeNull(),
    );
    expect(onSubmit).not.toHaveBeenCalled();

    // Plain text submits with no staged files attached.
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "hello" },
    });
    fireEvent.click(getSubmitButton(container));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const { message, options } = lastSubmit(onSubmit);
    expect(message.text).toBe("hello");
    expect(options?.additionalKwargs).toBeUndefined();
  });

  it("submits every pending shelf attachment when several were staged across a navigation", async () => {
    // Attaching the first document and navigating away unmounts the
    // composer; the project page appends the second one to the same pending
    // list. Both must reach the next message.
    stageProjectAttachment("thread-1", ATTACHMENT);
    stageProjectAttachment("thread-1", OTHER_ATTACHMENT);
    const onSubmit = rs.fn();
    const { container } = renderComposer({ onSubmit });

    await waitFor(() =>
      expect(screen.getAllByTestId("project-attachment-chip")).toHaveLength(2),
    );
    fireEvent.click(getSubmitButton(container));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const { options } = lastSubmit(onSubmit);
    expect(options?.additionalKwargs?.files).toEqual([
      STAGED_FILE,
      OTHER_STAGED_FILE,
    ]);
  });

  it("keeps a removed chip removed across a remount", async () => {
    stageProjectAttachment("thread-1", ATTACHMENT);
    stageProjectAttachment("thread-1", OTHER_ATTACHMENT);
    const onSubmit = rs.fn();
    const first = renderComposer({ onSubmit });

    await waitFor(() =>
      expect(screen.getAllByTestId("project-attachment-chip")).toHaveLength(2),
    );
    const [firstRemoveButton] = screen.getAllByLabelText(
      "Remove attached document",
    );
    if (!firstRemoveButton) {
      throw new Error("remove button not rendered");
    }
    fireEvent.click(firstRemoveButton);
    await waitFor(() =>
      expect(screen.getAllByTestId("project-attachment-chip")).toHaveLength(1),
    );

    first.unmount();
    const second = renderComposer({ onSubmit });
    await waitFor(() =>
      expect(screen.getAllByTestId("project-attachment-chip")).toHaveLength(1),
    );
    expect(screen.getByText(OTHER_ATTACHMENT.filename)).toBeTruthy();
    second.unmount();
  });

  it("resets the staged count after a sent message clears the chip", async () => {
    stageProjectAttachment("thread-1", ATTACHMENT);
    const onSubmit: SubmitSpy = rs.fn(
      (_message: unknown, options?: InputBoxSubmitOptions) => {
        options?.onSent?.();
      },
    );
    const { container } = renderComposer({ onSubmit });

    await screen.findByTestId("project-attachment-chip");
    fireEvent.click(getSubmitButton(container));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    // onSent cleared the staged attachments; a second empty submit is a
    // no-op again.
    await waitFor(() =>
      expect(screen.queryByTestId("project-attachment-chip")).toBeNull(),
    );
    fireEvent.click(getSubmitButton(container));
    await waitFor(() =>
      expect(screen.queryByTestId("project-attachment-chip")).toBeNull(),
    );
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
