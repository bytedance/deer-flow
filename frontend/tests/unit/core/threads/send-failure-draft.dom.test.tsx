import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
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
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import {
  buildComposerDraftKey,
  readComposerDraft,
} from "@/core/threads/composer-draft";
import { useThreadStream } from "@/core/threads/hooks";

// Drives the real composer through the real sendMessage, as the chat pages
// wire them. `thread.submit` only enqueues the SDK stream, so a rejected run
// request arrives later through the SDK's onError; the send must reject then,
// leaving the text and the stored draft for a retry (upstream #8039).

type StreamCallbacks = {
  onCreated?: (meta: { thread_id: string; run_id: string }) => void;
  onError?: (error: unknown, run?: unknown) => void;
};

const streamMock = rs.hoisted(() => ({
  submit: rs.fn(async () => undefined),
  callbacks: {} as StreamCallbacks,
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: StreamCallbacks) => {
    streamMock.callbacks = {
      onCreated: options.onCreated,
      onError: options.onError,
    };
    return {
      isLoading: false,
      messages: [],
      stop: rs.fn(async () => undefined),
      submit: streamMock.submit,
      values: { artifacts: [], messages: [], title: "", todos: [] },
    };
  },
}));

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

const draftKey = buildComposerDraftKey({
  userId: "user-1",
  threadId: "thread-1",
});
const storedDraft = () =>
  readComposerDraft(window.sessionStorage, draftKey)?.text;
const textbox = () => screen.getByRole<HTMLTextAreaElement>("textbox");

async function submitAndWaitForDispatch() {
  fireEvent.change(textbox(), { target: { value: "Keep this request" } });
  await waitFor(() => expect(storedDraft()).toBe("Keep this request"));
  fireEvent.submit(document.querySelector("form")!);
  await waitFor(() => expect(streamMock.submit).toHaveBeenCalledTimes(1));
}

beforeEach(() => {
  streamMock.submit.mockClear();
  streamMock.callbacks = {};
  rs.stubGlobal("fetch", async (input: unknown) => {
    const url = String(input);
    if (url.includes("/messages/page")) {
      return new Response(
        JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.includes("/api/skills")) {
      return new Response(JSON.stringify({ skills: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
});

afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  window.sessionStorage.clear();
});

it("keeps the composer text and persisted draft when the run request is rejected", async () => {
  renderChat();
  await submitAndWaitForDispatch();

  await act(async () => {
    streamMock.callbacks.onError?.(new Error("HTTP 502"), undefined);
  });

  // PromptInput keeps the text because the send rejected; the draft was never
  // retired at dispatch, so a reload restores it too.
  await waitFor(() => expect(textbox().value).toBe("Keep this request"));
  expect(storedDraft()).toBe("Keep this request");
  // Past the draft-save debounce: nothing may rewrite the rejected text away.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
  expect(storedDraft()).toBe("Keep this request");
});

it("clears the composer and the draft once the run is accepted", async () => {
  renderChat();
  await submitAndWaitForDispatch();

  await act(async () => {
    streamMock.callbacks.onCreated?.({
      thread_id: "thread-1",
      run_id: "run-1",
    });
  });

  await waitFor(() => expect(textbox().value).toBe(""));
  await waitFor(() => expect(storedDraft()).toBeUndefined());
});

it("does not reject an accepted send when its stream fails later", async () => {
  renderChat();
  await submitAndWaitForDispatch();

  await act(async () => {
    streamMock.callbacks.onCreated?.({
      thread_id: "thread-1",
      run_id: "run-1",
    });
    streamMock.callbacks.onError?.(new Error("stream dropped"), {
      thread_id: "thread-1",
      run_id: "run-1",
    });
  });

  // The accepted send cleared the composer; a later stream error must not put
  // the already-sent text back or resurrect the retired draft.
  await waitFor(() => expect(textbox().value).toBe(""));
  expect(storedDraft()).toBeUndefined();
});
