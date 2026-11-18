import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";

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

// Upstream #8039: pressing Stop after `thread.submit` resolved but before the
// Gateway acknowledged the run left `sendMessage` waiting for an acceptance
// frame that would never arrive, so the in-flight guard stayed set and the
// composer was stuck. Stopping must settle the send like an aborted attempt:
// the composer keeps its text and a retry can dispatch again.

type StreamCallbacks = {
  onCreated?: (meta: { thread_id: string; run_id: string }) => void;
  onError?: (error: unknown, run?: unknown) => void;
};

const streamMock = rs.hoisted(() => ({
  submit: rs.fn(async () => undefined),
  stop: rs.fn(async () => undefined),
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
      stop: streamMock.stop,
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

const sendOutcome: { error?: unknown } = {};

function ChatComposer() {
  // Mirrors the chat pages: the composer turns into "streaming" as soon as the
  // hook dispatches, and Stop goes through the hook's thread.stop.
  const [status, setStatus] = useState<"ready" | "streaming">("ready");
  const { sendMessage, isUploading, thread } = useThreadStream({
    context: DEFAULT_LOCAL_SETTINGS.context,
    isMock: false,
    threadId: "thread-1",
  });
  return (
    <InputBox
      threadId="thread-1"
      status={status}
      disabled={isUploading}
      context={{ mode: "flash" } as never}
      onStop={() => {
        setStatus("ready");
        void thread.stop();
      }}
      onSubmit={(message, options) => {
        setStatus("streaming");
        const promise = sendMessage("thread-1", message, undefined, options);
        promise.catch((error: unknown) => {
          sendOutcome.error = error;
        });
        return promise;
      }}
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

function submitButton(container: HTMLElement): HTMLButtonElement {
  const button = container.querySelector('button[type="submit"]');
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("submit button not rendered");
  }
  return button;
}

beforeEach(() => {
  streamMock.submit.mockClear();
  streamMock.stop.mockClear();
  streamMock.callbacks = {};
  sendOutcome.error = undefined;
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

it("settles a send stopped between submit and acceptance and keeps the draft", async () => {
  const { container } = renderChat();
  fireEvent.change(textbox(), { target: { value: "Stop me mid-send" } });
  await waitFor(() => expect(storedDraft()).toBe("Stop me mid-send"));
  fireEvent.submit(document.querySelector("form")!);
  await waitFor(() => expect(streamMock.submit).toHaveBeenCalledTimes(1));

  // Stop before any onCreated/content-location acknowledgement arrives.
  fireEvent.click(submitButton(container));
  await waitFor(() => expect(sendOutcome.error).toBeInstanceOf(Error));

  expect(streamMock.stop).toHaveBeenCalledTimes(1);
  // The send settled as an aborted attempt instead of hanging forever.
  expect((sendOutcome.error as Error).name).toBe("AbortError");
  expect(textbox().value).toBe("Stop me mid-send");
  expect(storedDraft()).toBe("Stop me mid-send");

  // The in-flight guard is released, so retrying dispatches a second send.
  fireEvent.submit(document.querySelector("form")!);
  await waitFor(() => expect(streamMock.submit).toHaveBeenCalledTimes(2));
});
