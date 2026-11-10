import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import type { UploadResponse } from "@/core/uploads/api";

// onSent tells callers they may drop one-time composer state (quotes,
// references, staged files, the stored draft). It fires only when the Gateway
// accepted the run: `thread.submit` merely enqueues the SDK stream, so a
// rejected run request arrives later through onError and the send rejects.

type StreamCallbacks = {
  onCreated?: (meta: { thread_id: string; run_id: string }) => void;
  onMetadataEvent?: (data: unknown) => void;
  onError?: (error: unknown, run?: unknown) => void;
};

const mocks = rs.hoisted(() => ({
  events: [] as string[],
  submit: rs.fn(async () => undefined),
  callbacks: {} as StreamCallbacks,
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: StreamCallbacks) => {
    mocks.callbacks = {
      onCreated: options.onCreated,
      onMetadataEvent: options.onMetadataEvent,
      onError: options.onError,
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

async function renderThreadStream(initialThreadId = "thread-1") {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    ({ threadId }: { threadId: string }) =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: false,
        threadId,
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
  mocks.submit.mockReset();
  mocks.submit.mockImplementation(async () => {
    mocks.events.push("submit");
  });
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
