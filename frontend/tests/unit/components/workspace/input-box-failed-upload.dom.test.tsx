import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { stageProjectAttachment } from "@/core/projects/composer-attach";
import type { AttachProjectDocumentResult } from "@/core/projects/types";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { useThreadStream } from "@/core/threads/hooks";
import type { UploadResponse } from "@/core/uploads/api";

// Drives the real composer through the real sendMessage, as the chat pages
// wire them, so a failed upload is observed where the user sees it.

const mocks = rs.hoisted(() => ({ submit: rs.fn(async () => undefined) }));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
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

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: () => ({
    isLoading: false,
    messages: [],
    stop: rs.fn(async () => undefined),
    submit: mocks.submit,
    values: { artifacts: [], messages: [], title: "", todos: [] },
  }),
}));

const ATTACHMENT: AttachProjectDocumentResult = {
  filename: "roadmap.md",
  size_bytes: 2048,
  virtual_path: "/mnt/user-data/uploads/roadmap.md",
  artifact_url:
    "/api/threads/thread-1/artifacts/mnt/user-data/uploads/roadmap.md",
};

const UPLOAD_RESPONSE: UploadResponse = {
  success: true,
  files: [
    {
      filename: "notes.txt",
      size: 5,
      path: "/data/uploads/notes.txt",
      virtual_path: "/mnt/user-data/uploads/notes.txt",
      artifact_url: "/api/threads/thread-1/artifacts/notes.txt",
    },
  ],
  message: "ok",
  skipped_files: [],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function ChatComposer() {
  const { sendMessage, isUploading } = useThreadStream({
    context: DEFAULT_LOCAL_SETTINGS.context,
    isMock: false,
    threadId: "thread-1",
  });
  return (
    <InputBox
      threadId="thread-1"
      status="ready"
      disabled={isUploading}
      context={{ mode: "flash" } as never}
      onSubmit={(message, options) =>
        sendMessage("thread-1", message, undefined, options)
      }
    />
  );
}

function renderChat() {
  return render(
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
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
            value={{ thread: { messages: [] } as never, isMock: false }}
          >
            <PromptInputProvider>
              <ChatComposer />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

let uploadAttempts = 0;

beforeEach(() => {
  uploadAttempts = 0;
  mocks.submit.mockClear();
  // happy-dom's File is not a Node Blob, so the composer's preview URL needs
  // a stand-in.
  rs.spyOn(URL, "createObjectURL").mockReturnValue("blob:attachment");
  rs.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  rs.stubGlobal("fetch", async (input: unknown) => {
    const url = String(input);
    if (/\/api\/threads\/[^/]+\/uploads$/.test(url)) {
      uploadAttempts += 1;
      return uploadAttempts === 1
        ? json({ detail: "disk full" }, 500)
        : json(UPLOAD_RESPONSE);
    }
    if (/\/runs(\?|$)/.test(url)) {
      return json([]);
    }
    return json({ data: [], has_more: false, next_before_seq: null });
  });
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.unstubAllGlobals();
  window.sessionStorage.clear();
});

it("retries a failed upload with the staged project attachment still attached", async () => {
  stageProjectAttachment("thread-1", ATTACHMENT);
  const { container } = renderChat();
  await screen.findByTestId("project-attachment-chip");
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "summarize it" },
  });
  fireEvent.change(document.querySelector('input[type="file"]')!, {
    target: {
      files: [new File(["notes"], "notes.txt", { type: "text/plain" })],
    },
  });
  await screen.findByText("notes.txt");

  fireEvent.submit(container.querySelector("form")!);
  await waitFor(() => expect(uploadAttempts).toBe(1));
  await waitFor(() =>
    expect(screen.getByRole<HTMLTextAreaElement>("textbox").disabled).toBe(
      false,
    ),
  );

  expect(mocks.submit).not.toHaveBeenCalled();
  expect(screen.getByTestId("project-attachment-chip")).toBeTruthy();

  fireEvent.submit(container.querySelector("form")!);
  await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));
  const [input] = mocks.submit.mock.calls[0] as unknown as [
    {
      messages: Array<{
        content: unknown;
        additional_kwargs?: { files?: Array<{ path?: string }> };
      }>;
    },
  ];
  const sent = input.messages.at(-1);
  expect(sent?.additional_kwargs?.files?.map((file) => file.path)).toEqual([
    ATTACHMENT.virtual_path,
    "/mnt/user-data/uploads/notes.txt",
  ]);
});
