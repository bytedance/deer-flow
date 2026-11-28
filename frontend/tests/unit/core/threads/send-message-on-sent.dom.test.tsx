import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { markRunError } from "@/core/threads/run-error";
import { markThreadCreation } from "@/core/threads/thread-creation";
import type { UploadResponse } from "@/core/uploads/api";
import { AttachmentUploadSession } from "@/core/uploads/attachment-upload-session";

// onSent tells callers they may drop one-time composer state (quotes,
// references, staged files, the stored draft). It fires only when the Gateway
// accepted the run: `thread.submit` merely enqueues the SDK stream, so a
// rejected run request arrives later through onError and the send rejects.

type StreamCallbacks = {
  onCreated?: (meta: { thread_id: string; run_id: string }) => void;
  onMetadataEvent?: (data: unknown) => void;
  onError?: (error: unknown, run?: unknown) => void;
  onFinish?: (state: { values: unknown }, run?: unknown) => void;
  onThreadId?: (threadId: string) => void;
};

const mocks = rs.hoisted(() => ({
  events: [] as string[],
  submit: rs.fn(async () => undefined),
  callbacks: {} as StreamCallbacks,
  toastError: rs.fn(),
}));

rs.mock("sonner", () => ({ toast: { error: mocks.toastError } }));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: StreamCallbacks) => {
    mocks.callbacks = {
      onCreated: options.onCreated,
      onMetadataEvent: options.onMetadataEvent,
      onError: options.onError,
      onFinish: options.onFinish,
      onThreadId: options.onThreadId,
    };
    return {
      isLoading: false,
      messages: [],
      stop: rs.fn(async () => undefined),
      submit: mocks.submit,
      values: { artifacts: [], messages: [], title: "", todos: [] },
    };
  },
}));

const UPLOAD_RESPONSE: UploadResponse = {
  success: true,
  files: [
    {
      filename: "report.pdf",
      size: 42,
      path: "/data/uploads/report.pdf",
      virtual_path: "/mnt/user-data/uploads/report.pdf",
      artifact_url: "/api/threads/thread-1/artifacts/report.pdf",
    },
  ],
  message: "ok",
  skipped_files: [],
};

const MESSAGE_WITH_FILE: PromptInputMessage = {
  text: "Compare these",
  files: [
    {
      type: "file",
      url: "blob:report",
      mediaType: "application/pdf",
      filename: "report.pdf",
      file: new File(["%PDF"], "report.pdf", { type: "application/pdf" }),
    },
  ],
};

function stubUploadFetch(upload: () => Promise<Response>) {
  rs.stubGlobal("fetch", async (input: unknown) => {
    const url = String(input);
    if (/\/api\/threads\/[^/]+\/uploads$/.test(url)) {
      mocks.events.push("upload");
      return upload();
    }
    if (/\/api\/threads\/[^/]+\/messages\/page/.test(url)) {
      return new Response(
        JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

function createWrapper(queryClient: QueryClient) {
  return function SendMessageTestWrapper({
    children,
  }: {
    children: ReactNode;
  }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        I18nContext.Provider,
        {
          value: { locale: "en-US", setLocale: () => undefined, t: enUS },
        },
        children,
      ),
    );
  };
}

async function flushFrames() {
  for (let index = 0; index < 6; index += 1) {
    await act(async () => undefined);
  }
}

async function renderThreadStream(initialThreadId: string | null = "thread-1") {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    ({ threadId }: { threadId: string | null }) =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: false,
        threadId: threadId ?? undefined,
      }),
    {
      initialProps: { threadId: initialThreadId },
      wrapper: createWrapper(
        new QueryClient({ defaultOptions: { queries: { retry: false } } }),
      ),
    },
  );
  await flushFrames();
  return rendered;
}

beforeEach(() => {
  mocks.events = [];
  mocks.callbacks = {};
  mocks.toastError.mockReset();
  mocks.submit.mockReset();
  mocks.submit.mockImplementation(async () => {
    mocks.events.push("submit");
  });
});

test("does not replace a file failure whose message matches a session diagnostic", async () => {
  stubUploadFetch(async () => new Response("{}"));
  const { result } = await renderThreadStream();
  const cause = new Error("Attachments are not ready");
  const attachmentUploads = new AttachmentUploadSession(async () => {
    throw cause;
  });
  const onSent = rs.fn();
  await act(async () => {
    await expect(
      result.current.sendMessage("thread-1", MESSAGE_WITH_FILE, undefined, {
        attachmentUploads,
        onSent,
      }),
    ).rejects.toMatchObject({ code: "failed", cause });
  });
  expect(mocks.toastError).toHaveBeenCalledWith(cause.message);
  expect(mocks.submit).not.toHaveBeenCalled();
  expect(onSent).not.toHaveBeenCalled();
});

test("localizes a session state error using its type", async () => {
  stubUploadFetch(async () => new Response("{}"));
  const { result } = await renderThreadStream();
  const attachmentUploads = new AttachmentUploadSession();
  attachmentUploads.deactivate();
  await act(async () => {
    await expect(
      result.current.sendMessage("thread-1", MESSAGE_WITH_FILE, undefined, {
        attachmentUploads,
      }),
    ).rejects.toMatchObject({ code: "inactive" });
  });
  expect(mocks.toastError).toHaveBeenCalledWith(enUS.uploads.notReady);
  expect(mocks.submit).not.toHaveBeenCalled();
});

afterEach(() => {
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
});

async function acceptRun() {
  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "thread-1", run_id: "run-1" });
  });
}

test("ignores an acceptance frame that names another thread", async () => {
  const { result } = await renderThreadStream();
  const onSent = rs.fn();

  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "thread-1",
      { text: "hi", files: [] },
      undefined,
      { onSent },
    );
  });
  await flushFrames();

  // A frame from an older stream names its own thread; accepting it here would
  // retire this send's draft even though its own run was never acknowledged.
  await act(async () => {
    mocks.callbacks.onMetadataEvent?.({
      thread_id: "thread-2",
      run_id: "run-2",
    });
  });
  await flushFrames();
  expect(onSent).not.toHaveBeenCalled();

  await acceptRun();
  await act(async () => {
    await sendPromise;
  });
  expect(onSent).toHaveBeenCalledTimes(1);
});

test("does not report a send whose attachment upload fails", async () => {
  stubUploadFetch(
    async () =>
      new Response(JSON.stringify({ detail: "disk full" }), { status: 500 }),
  );
  const { result } = await renderThreadStream();
  const onSent = rs.fn();

  let sendError: unknown;
  await act(async () => {
    await result.current
      .sendMessage("thread-1", MESSAGE_WITH_FILE, undefined, { onSent })
      .catch((error: unknown) => {
        sendError = error;
      });
  });

  expect(sendError).toBeInstanceOf(Error);
  expect(mocks.events).toEqual(["upload"]);
  expect(onSent).not.toHaveBeenCalled();
});

test("reports the send after its attachments upload and the run is accepted", async () => {
  let finishUpload!: () => void;
  stubUploadFetch(
    () =>
      new Promise<Response>((resolve) => {
        finishUpload = () =>
          resolve(
            new Response(JSON.stringify(UPLOAD_RESPONSE), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
      }),
  );
  const { result } = await renderThreadStream();
  const onSent = rs.fn(() => {
    mocks.events.push("onSent");
  });

  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "thread-1",
      MESSAGE_WITH_FILE,
      undefined,
      { onSent },
    );
  });
  await flushFrames();
  expect(onSent).not.toHaveBeenCalled();

  finishUpload();
  await flushFrames();
  // Dispatch alone is not delivery: the run is submitted, but nothing is
  // retired until the Gateway acknowledges it.
  expect(mocks.events).toEqual(["upload", "submit"]);
  expect(onSent).not.toHaveBeenCalled();

  await acceptRun();
  await act(async () => {
    await sendPromise;
  });

  expect(mocks.events).toEqual(["upload", "submit", "onSent"]);
  expect(onSent).toHaveBeenCalledTimes(1);
});

test("reports a text-only send once the run is accepted", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result } = await renderThreadStream();
  const onSent = rs.fn(() => {
    mocks.events.push("onSent");
  });

  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "thread-1",
      { text: "Hello", files: [] },
      undefined,
      { onSent },
    );
  });
  await flushFrames();
  expect(mocks.events).toEqual(["submit"]);
  expect(onSent).not.toHaveBeenCalled();

  await acceptRun();
  await act(async () => {
    await sendPromise;
  });

  expect(mocks.events).toEqual(["submit", "onSent"]);
});

test("rejects a send whose run request fails before the run exists", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result } = await renderThreadStream();
  const onSent = rs.fn(() => {
    mocks.events.push("onSent");
  });

  let sendError: unknown;
  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current
      .sendMessage("thread-1", { text: "Hello", files: [] }, undefined, {
        onSent,
      })
      .catch((error: unknown) => {
        sendError = error;
      });
  });
  await flushFrames();
  expect(mocks.events).toEqual(["submit"]);

  await act(async () => {
    mocks.callbacks.onError?.(new Error("HTTP 502"), undefined);
  });
  await act(async () => {
    await sendPromise;
  });

  expect(sendError).toBeInstanceOf(Error);
  expect(onSent).not.toHaveBeenCalled();
});

test("does not retire a second time when an accepted send fails later", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result } = await renderThreadStream();
  const onSent = rs.fn(() => {
    mocks.events.push("onSent");
  });

  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "thread-1",
      { text: "Hello", files: [] },
      undefined,
      { onSent },
    );
  });
  await flushFrames();
  await acceptRun();
  await act(async () => {
    await sendPromise;
  });
  await act(async () => {
    mocks.callbacks.onError?.(new Error("stream dropped"), {
      thread_id: "thread-1",
      run_id: "run-1",
    });
  });

  expect(onSent).toHaveBeenCalledTimes(1);
  expect(mocks.events).toEqual(["submit", "onSent"]);
});

test("retires a released send when the run is accepted after the view moved on", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result, rerender } = await renderThreadStream();
  const onSent = rs.fn(() => {
    mocks.events.push("onSent");
  });

  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "thread-1",
      { text: "Hello", files: [] },
      undefined,
      { onSent },
    );
  });
  await flushFrames();
  expect(mocks.events).toEqual(["submit"]);

  // The view switches before acceptance: the caller is released, but the
  // one-time state is not retired yet because no run was acknowledged.
  rerender({ threadId: "thread-2" });
  await flushFrames();
  await act(async () => {
    await sendPromise;
  });
  expect(onSent).not.toHaveBeenCalled();

  // Acceptance arrives for the abandoned conversation afterwards; its stored
  // draft and staged files must still be retired, exactly once.
  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "thread-1", run_id: "run-1" });
  });
  expect(onSent).toHaveBeenCalledTimes(1);

  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "thread-1", run_id: "run-1" });
  });
  expect(onSent).toHaveBeenCalledTimes(1);
});

test("does not retire a released new-chat send when another chat is accepted", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result, rerender } = await renderThreadStream(null);
  const onSentA = rs.fn(() => {
    mocks.events.push("onSentA");
  });
  const onSentB = rs.fn(() => {
    mocks.events.push("onSentB");
  });

  // Chat A: a new conversation, so the page submits a placeholder id and the
  // SDK creates the thread, which it reports through onThreadId.
  let sendA: Promise<unknown> | undefined;
  act(() => {
    sendA = result.current.sendMessage(
      "placeholder-a",
      { text: "Hello from A", files: [] },
      undefined,
      { onSent: onSentA },
    );
  });
  await flushFrames();
  await act(async () => {
    mocks.callbacks.onThreadId?.("server-a");
  });

  // Navigate away before A's run is accepted pattern: the caller is released.
  rerender({ threadId: "thread-other" });
  await flushFrames();
  await act(async () => {
    await sendA;
  });
  expect(onSentA).not.toHaveBeenCalled();

  // Chat B starts another new conversation and its run is accepted. That frame
  // must not retire A's draft: A's run was never acknowledged.
  rerender({ threadId: null });
  await flushFrames();
  let sendB: Promise<unknown> | undefined;
  act(() => {
    sendB = result.current.sendMessage(
      "placeholder-b",
      { text: "Hello from B", files: [] },
      undefined,
      { onSent: onSentB },
    );
  });
  await flushFrames();
  await act(async () => {
    mocks.callbacks.onThreadId?.("server-b");
  });
  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "server-b", run_id: "run-b" });
  });
  await act(async () => {
    await sendB;
  });

  expect(onSentA).not.toHaveBeenCalled();
  expect(onSentB).toHaveBeenCalledTimes(1);
});

test("drops a released new-chat send whose run request failed before its thread was reported", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result, rerender } = await renderThreadStream(null);
  const onSentA = rs.fn(() => {
    mocks.events.push("onSentA");
  });
  const onSentB = rs.fn(() => {
    mocks.events.push("onSentB");
  });

  // Chat A is submitted and released on navigation before the SDK reports the
  // thread it would create, so the send stays unnamed.
  let sendA: Promise<unknown> | undefined;
  act(() => {
    sendA = result.current.sendMessage(
      "placeholder-a",
      { text: "Hello from A", files: [] },
      undefined,
      { onSent: onSentA },
    );
  });
  await flushFrames();
  rerender({ threadId: "thread-other" });
  await flushFrames();
  await act(async () => {
    await sendA;
  });

  // Its run request is then refused. The draft stays (the run never started),
  // but the record must not survive to claim a later acceptance or to bind the
  // next new chat's created thread to itself.
  const refusal = new Error("HTTP 500");
  markRunError(refusal, "placeholder-a");
  await act(async () => {
    mocks.callbacks.onError?.(refusal, undefined);
  });
  expect(onSentA).not.toHaveBeenCalled();

  // Chat B starts another new conversation; its own run is accepted and both
  // its thread binding and its acceptance must belong to B alone.
  rerender({ threadId: null });
  await flushFrames();
  let sendB: Promise<unknown> | undefined;
  act(() => {
    sendB = result.current.sendMessage(
      "placeholder-b",
      { text: "Hello from B", files: [] },
      undefined,
      { onSent: onSentB },
    );
  });
  await flushFrames();
  await act(async () => {
    mocks.callbacks.onThreadId?.("server-b");
  });
  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "server-b", run_id: "run-b" });
  });
  await act(async () => {
    await sendB;
  });

  expect(onSentA).not.toHaveBeenCalled();
  expect(onSentB).toHaveBeenCalledTimes(1);
});

test("resolves an accepted send whose onSent throws and reports the failure", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const consoleError = rs
    .spyOn(console, "error")
    .mockImplementation(() => undefined);
  const failure = new Error("draft cleanup failed");
  const onSent = rs.fn(() => {
    throw failure;
  });
  const { result } = await renderThreadStream();

  let settled = false;
  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current
      .sendMessage("thread-1", { text: "Hello", files: [] }, undefined, {
        onSent,
      })
      .then(() => {
        settled = true;
      });
  });
  await flushFrames();
  await acceptRun();
  await act(async () => {
    await sendPromise;
  });

  // The caller must not wait forever on a throwing cleanup, and the failure
  // must stay visible instead of being swallowed.
  expect(settled).toBe(true);
  expect(onSent).toHaveBeenCalledTimes(1);
  expect(consoleError).toHaveBeenCalledWith(
    "Failed to retire one-time composer state for an accepted send.",
    failure,
  );
});
test("binds the thread the SDK creates for a send that carried a display id", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  // The sidecar's chat is created by the gateway, but the stream hook has not
  // adopted it yet when the send goes out, so the SDK creates the thread and
  // reports it through onThreadId. That report must belong to this send even
  // though it was submitted with a thread id.
  const { result } = await renderThreadStream("display-thread");
  const onSent = rs.fn();
  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "display-thread",
      { text: "Hello from the side chat", files: [] },
      undefined,
      { onSent },
    );
  });
  await flushFrames();

  await act(async () => {
    mocks.callbacks.onThreadId?.("server-created");
  });
  await act(async () => {
    mocks.callbacks.onCreated?.({
      thread_id: "server-created",
      run_id: "run-created",
    });
  });

  expect(onSent).toHaveBeenCalledTimes(1);
  await act(async () => {
    await sendPromise;
  });
});

test("does not reject a newer send when an older released send's request fails", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result, rerender } = await renderThreadStream("thread-1");
  const onSentA = rs.fn();
  const onSentB = rs.fn();

  // A is submitted, then released when the view moves to another chat.
  let sendA: Promise<unknown> | undefined;
  act(() => {
    sendA = result.current.sendMessage(
      "thread-1",
      { text: "Hello from A", files: [] },
      undefined,
      { onSent: onSentA },
    );
  });
  await flushFrames();
  rerender({ threadId: "thread-2" });
  await flushFrames();
  await act(async () => {
    await sendA;
  });

  // B is submitted in the chat now on screen. A's refused request then arrives
  // without run metadata, tagged with A's thread: it belongs to A, so B must
  // keep waiting for its own acceptance instead of rejecting with A's error.
  let sendB: Promise<unknown> | undefined;
  act(() => {
    sendB = result.current.sendMessage(
      "thread-2",
      { text: "Hello from B", files: [] },
      undefined,
      { onSent: onSentB },
    );
  });
  await flushFrames();
  const refusalForA = new Error("HTTP 422");
  markRunError(refusalForA, "thread-1");
  await act(async () => {
    mocks.callbacks.onError?.(refusalForA, undefined);
  });
  expect(onSentB).not.toHaveBeenCalled();

  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "thread-2", run_id: "run-2" });
  });
  expect(onSentB).toHaveBeenCalledTimes(1);
  expect(onSentA).not.toHaveBeenCalled();
  await act(async () => {
    await sendB;
  });
});

test("rejects the mounted send when its own request is refused after a release", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result, rerender } = await renderThreadStream("thread-1");
  const onSentA = rs.fn();
  const onSentB = rs.fn();

  // A is released on navigation. Its request may end without any callback (the
  // SDK clears the stream silently), so it must not consume B's refusal.
  let sendA: Promise<unknown> | undefined;
  act(() => {
    sendA = result.current.sendMessage(
      "thread-1",
      { text: "Hello from A", files: [] },
      undefined,
      { onSent: onSentA },
    );
  });
  await flushFrames();
  rerender({ threadId: "thread-2" });
  await flushFrames();
  await act(async () => {
    await sendA;
  });

  // B's own run request is refused. The refusal is tagged with B's thread, so
  // B rejects with it and keeps its draft; A is not discarded by B's error.
  let sendB: Promise<unknown> | undefined;
  let sendBError: unknown;
  act(() => {
    sendB = result.current
      .sendMessage("thread-2", { text: "Hello from B", files: [] }, undefined, {
        onSent: onSentB,
      })
      .catch((error: unknown) => {
        sendBError = error;
      });
  });
  await flushFrames();
  const refusalForB = new Error("HTTP 422");
  markRunError(refusalForB, "thread-2");
  await act(async () => {
    mocks.callbacks.onError?.(refusalForB, undefined);
  });
  await act(async () => {
    await sendB;
  });
  expect(sendBError).toBe(refusalForB);
  expect(onSentB).not.toHaveBeenCalled();

  // A still retires its draft when its own acceptance arrives afterwards.
  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "thread-1", run_id: "run-1" });
  });
  expect(onSentA).toHaveBeenCalledTimes(1);
});
test("binds a created thread to the send that asked for it, not a released one", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result, rerender } = await renderThreadStream(null);
  const onSentA = rs.fn();
  const onSentB = rs.fn();

  // A is submitted in a new chat and released before the SDK reports the
  // thread it would create; its request is then cancelled silently.
  let sendA: Promise<unknown> | undefined;
  act(() => {
    sendA = result.current.sendMessage(
      "placeholder-a",
      { text: "Hello from A", files: [] },
      undefined,
      { onSent: onSentA },
    );
  });
  await flushFrames();
  rerender({ threadId: "thread-other" });
  await flushFrames();
  await act(async () => {
    await sendA;
  });

  // B is sent in another new chat. The SDK reports the thread it created for B,
  // and that report names the submission that asked for it, so it must bind B.
  rerender({ threadId: null });
  await flushFrames();
  let sendB: Promise<unknown> | undefined;
  act(() => {
    sendB = result.current.sendMessage(
      "placeholder-b",
      { text: "Hello from B", files: [] },
      undefined,
      { onSent: onSentB },
    );
  });
  await flushFrames();
  markThreadCreation("server-b", "placeholder-b");
  await act(async () => {
    mocks.callbacks.onThreadId?.("server-b");
  });
  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "server-b", run_id: "run-b" });
  });
  await act(async () => {
    await sendB;
  });

  expect(onSentB).toHaveBeenCalledTimes(1);
  expect(onSentA).not.toHaveBeenCalled();
});
test("accepts a frame that names the submitted id after the SDK created another thread", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  // The sidecar's gateway-created chat is submitted before useStream adopts it,
  // so the SDK creates its own conversation. The Gateway reports the run under
  // the id the caller submitted, which is this send's own identity too.
  const { result, rerender } = await renderThreadStream(null);
  const onSent = rs.fn();
  rerender({ threadId: "sidecar-thread" });
  await flushFrames();

  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "sidecar-thread",
      { text: "What tradeoffs should we consider?", files: [] },
      undefined,
      { onSent },
    );
  });
  await flushFrames();
  markThreadCreation("server-created", "sidecar-thread");
  await act(async () => {
    mocks.callbacks.onThreadId?.("server-created");
  });
  await act(async () => {
    mocks.callbacks.onCreated?.({
      thread_id: "sidecar-thread",
      run_id: "run-sidecar",
    });
  });
  await act(async () => {
    await sendPromise;
  });

  expect(onSent).toHaveBeenCalledTimes(1);
});

test("settles a send whose stream finishes without run metadata", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result } = await renderThreadStream("thread-1");
  const onSent = rs.fn();
  let send: Promise<unknown> | undefined;
  act(() => {
    send = result.current.sendMessage(
      "thread-1",
      { text: "Hello", files: [] },
      undefined,
      { onSent },
    );
  });
  await flushFrames();

  // The SDK can finish a stream that created its run without reporting that
  // run; an empty frame id must still settle this hook's own send, or the
  // composer stays locked for every later send on this instance.
  await act(async () => {
    mocks.callbacks.onFinish?.({ values: { messages: [] } }, undefined);
  });
  await act(async () => {
    await send;
  });
  expect(onSent).toHaveBeenCalledTimes(1);

  act(() => {
    void result.current.sendMessage("thread-1", { text: "Again", files: [] });
  });
  await flushFrames();
  expect(mocks.events.filter((event) => event === "submit")).toHaveLength(2);
});

test("drops a released new-chat send when its server thread is used again", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result, rerender } = await renderThreadStream(null);
  const onSentA = rs.fn();
  const onSentB = rs.fn();

  // A is a new chat: the page submits a placeholder and the SDK reports the
  // thread it created.
  let sendA: Promise<unknown> | undefined;
  act(() => {
    sendA = result.current.sendMessage(
      "placeholder-a",
      { text: "Hello from A", files: [] },
      undefined,
      { onSent: onSentA },
    );
  });
  await flushFrames();
  await act(async () => {
    mocks.callbacks.onThreadId?.("server-a");
  });

  // Navigate away before A's run is accepted.
  rerender({ threadId: "thread-other" });
  await flushFrames();
  await act(async () => {
    await sendA;
  });
  expect(onSentA).not.toHaveBeenCalled();

  // B continues the same conversation A was bound to. A's attempt superseded
  // B on this conversation, so B's acceptance must not retire A's draft.
  rerender({ threadId: "server-a" });
  await flushFrames();
  let sendB: Promise<unknown> | undefined;
  act(() => {
    sendB = result.current.sendMessage(
      "server-a",
      { text: "Hello from B", files: [] },
      undefined,
      { onSent: onSentB },
    );
  });
  await flushFrames();
  await act(async () => {
    mocks.callbacks.onCreated?.({ thread_id: "server-a", run_id: "run-b" });
  });
  await act(async () => {
    await sendB;
  });

  expect(onSentA).not.toHaveBeenCalled();
  expect(onSentB).toHaveBeenCalledTimes(1);
});
