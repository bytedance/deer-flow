import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { toast } from "sonner";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { stageProjectAttachment } from "@/core/projects/composer-attach";
import type { AttachProjectDocumentResult } from "@/core/projects/types";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import {
  buildComposerDraftKey,
  readComposerDraft,
} from "@/core/threads/composer-draft";
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

it("keeps the draft through a failed upload and a busy /goal, then runs the goal's objective once", async () => {
  // A /goal the Gateway refuses with 409 never reaches sendMessage, so like
  // a failed upload it must leave the composer and its stored draft alone.
  const goalStatuses: number[] = [];
  const baseFetch = globalThis.fetch;
  rs.stubGlobal("fetch", async (input: unknown, init?: RequestInit) => {
    if (String(input).endsWith("/api/threads/thread-1/goal")) {
      const status = goalStatuses.length === 0 ? 409 : 200;
      goalStatuses.push(status);
      return status === 409
        ? json({ detail: "Thread has a run in flight." }, 409)
        : json({ goal: { objective: "finish all tests", status: "active" } });
    }
    return baseFetch(input as RequestInfo, init);
  });
  const error = rs.spyOn(toast, "error");
  const draftKey = buildComposerDraftKey({
    userId: "user-1",
    threadId: "thread-1",
  });
  const storedDraft = () =>
    readComposerDraft(window.sessionStorage, draftKey)?.text;
  const textbox = () => screen.getByRole<HTMLTextAreaElement>("textbox");
  const { container } = renderChat();
  const submit = () => fireEvent.submit(container.querySelector("form")!);

  fireEvent.change(textbox(), { target: { value: "summarize it" } });
  fireEvent.change(document.querySelector('input[type="file"]')!, {
    target: {
      files: [new File(["notes"], "notes.txt", { type: "text/plain" })],
    },
  });
  await screen.findByText("notes.txt");
  await waitFor(() => expect(storedDraft()).toBe("summarize it"));
  submit();
  await waitFor(() => expect(uploadAttempts).toBe(1));
  await waitFor(() => expect(textbox().disabled).toBe(false));
  expect(textbox().value).toBe("summarize it");
  expect(storedDraft()).toBe("summarize it");

  fireEvent.click(screen.getByRole("button", { name: "Remove attachment" }));
  fireEvent.change(textbox(), {
    target: { value: "/goal finish all tests" },
  });
  await waitFor(() => expect(storedDraft()).toBe("/goal finish all tests"));
  submit();
  await waitFor(() =>
    expect(error).toHaveBeenCalledWith(enUS.inputBox.goalBar.busy),
  );
  // Let PromptInput settle the rejected submit before reading the composer.
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(textbox().value).toBe("/goal finish all tests");
  expect(storedDraft()).toBe("/goal finish all tests");
  expect(mocks.submit).not.toHaveBeenCalled();

  submit();
  await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));
  expect(goalStatuses).toEqual([409, 200]);
  expect(uploadAttempts).toBe(1);
  const [input] = mocks.submit.mock.calls[0] as unknown as [
    {
      messages: Array<{
        content: unknown;
        additional_kwargs?: { files?: unknown };
      }>;
    },
  ];
  const sent = input.messages.at(-1);
  expect(JSON.stringify(sent?.content)).toContain("finish all tests");
  expect(JSON.stringify(sent?.content)).not.toContain("/goal");
  expect(sent?.additional_kwargs?.files).toBeUndefined();
  await waitFor(() => expect(textbox().value).toBe(""));
  // Past the draft-save delay: nothing writes the sent text back.
  await new Promise((resolve) => setTimeout(resolve, 400));
  expect(storedDraft()).toBeUndefined();
});
