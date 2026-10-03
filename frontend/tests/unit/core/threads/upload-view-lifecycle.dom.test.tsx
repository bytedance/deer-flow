import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement, StrictMode, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { useThreadStream } from "@/core/threads/hooks";

type StartEvent = {
  viewThreadId: string;
  createdThreadId: string;
  runId: string;
};

type HookProps = {
  threadId: string | undefined;
  displayThreadId: string;
  onStart: (event: StartEvent) => void;
};

type RunRequest = {
  threadId: string | null;
  body: unknown;
};

type UploadResponse = {
  success: boolean;
  files: {
    filename: string;
    size: number;
    path: string;
    virtual_path: string;
    artifact_url: string;
  }[];
  message: string;
  skipped_files: string[];
};

const uploadResponse: UploadResponse = {
  success: true,
  files: [
    {
      filename: "brief.txt",
      size: 5,
      path: "/data/uploads/brief.txt",
      virtual_path: "/mnt/user-data/uploads/brief.txt",
      artifact_url: "/api/threads/thread-a/artifacts/brief.txt",
    },
  ],
  message: "ok",
  skipped_files: [],
};

const queryClients: QueryClient[] = [];
let activeFetchImplementation:
  | ((input: RequestInfo | URL, init?: RequestInit) => Promise<Response>)
  | undefined;
const originalWindowFetch = window.fetch;
const routedFetch: typeof fetch = (async (
  input: RequestInfo | URL,
  init?: RequestInit,
) => {
  if (!activeFetchImplementation) {
    throw new Error("No upload lifecycle fetch controller is active.");
  }
  return activeFetchImplementation(input, init);
}) as typeof fetch;

function createWrapper(queryClient: QueryClient, strictMode = false) {
  return function ThreadStreamTestWrapper({
    children,
  }: {
    children: ReactNode;
  }) {
    const providers = createElement(
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
    return strictMode ? createElement(StrictMode, null, providers) : providers;
  };
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function threadState(threadId: string) {
  return {
    values: { artifacts: [], messages: [], title: "", todos: [] },
    next: [],
    tasks: [],
    metadata: {},
    checkpoint: {
      thread_id: threadId,
      checkpoint_id: "checkpoint-" + threadId,
      checkpoint_ns: "",
    },
    parent_checkpoint: null,
    created_at: "2026-10-02T00:00:00Z",
  };
}

function deferred<T>() {
  let resolvePromise: (value: T | PromiseLike<T>) => void = (value) => {
    void value;
  };
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

function createFetchController(
  options: { holdFirstRunResponse?: boolean } = {},
) {
  const uploadStarted = deferred<void>();
  const secondUploadStarted = deferred<void>();
  const uploadResponseReady = deferred<void>();
  const secondUploadResponseReady = deferred<void>();
  const runRequestStarted = deferred<void>();
  const secondRunRequestStarted = deferred<void>();
  const firstRunResponseReady = deferred<void>();
  const firstRunResponsePulled = deferred<void>();
  const secondRunResponsePulled = deferred<void>();
  const runRequests: RunRequest[] = [];
  let uploadCount = 0;
  let threadCreateCount = 0;

  const fetchFn = async (input: RequestInfo | URL, init?: RequestInit) => {
    const rawUrl =
      typeof input === "string" || input instanceof URL
        ? input.toString()
        : input.url;
    const url = new URL(rawUrl, window.location.origin);
    const method = (init?.method ?? "GET").toUpperCase();

    if (url.pathname.endsWith("/uploads")) {
      uploadCount += 1;
      if (uploadCount === 1) {
        uploadStarted.resolve();
        await uploadResponseReady.promise;
      } else if (uploadCount === 2) {
        secondUploadStarted.resolve();
        await secondUploadResponseReady.promise;
      }
      return jsonResponse(uploadResponse);
    }

    if (method === "POST" && url.pathname.endsWith("/runs/stream")) {
      const streamPathMatch = /\/threads\/([^/]+)\/runs\/stream$/.exec(
        url.pathname,
      );
      const threadId = streamPathMatch?.[1] ?? null;
      const runIndex = runRequests.length + 1;
      const runId = "run-" + String(runIndex);
      let body: unknown = null;
      if (typeof init?.body === "string") {
        body = JSON.parse(init.body);
      }
      runRequests.push({ threadId, body });
      if (runIndex === 1) {
        runRequestStarted.resolve();
        if (options.holdFirstRunResponse) {
          await firstRunResponseReady.promise;
        }
      } else if (runIndex === 2) {
        secondRunRequestStarted.resolve();
      }
      const contentLocation = threadId
        ? "/threads/" + threadId + "/runs/" + runId
        : "/runs/" + runId;
      const responsePulled =
        runIndex === 1 ? firstRunResponsePulled : secondRunResponsePulled;
      const responseBody = new ReadableStream<Uint8Array>(
        {
          pull(controller) {
            responsePulled.resolve();
            controller.enqueue(
              new TextEncoder().encode("event: end\ndata: null\n\n"),
            );
            controller.close();
          },
        },
        { highWaterMark: 0 },
      );
      return new Response(responseBody, {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Content-Location": contentLocation,
        },
      });
    }

    if (method === "POST" && url.pathname.endsWith("/threads")) {
      threadCreateCount += 1;
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as { thread_id?: string })
          : {};
      return jsonResponse({ thread_id: body.thread_id ?? "thread-created" });
    }

    if (url.pathname.endsWith("/messages/page")) {
      return jsonResponse({
        data: [],
        has_more: false,
        next_before_seq: null,
      });
    }

    const threadPathMatch = /\/threads\/([^/]+)/.exec(url.pathname);
    const threadId = threadPathMatch?.[1];
    if (url.pathname.endsWith("/history")) {
      return jsonResponse(threadId ? [threadState(threadId)] : []);
    }
    if (url.pathname.endsWith("/state")) {
      return jsonResponse(threadState(threadId ?? "thread-unknown"));
    }
    if (method === "GET" && url.pathname.endsWith("/runs")) {
      return jsonResponse([]);
    }

    return jsonResponse({});
  };

  activeFetchImplementation = fetchFn;
  rs.stubGlobal("fetch", routedFetch);
  window.fetch = routedFetch;

  return {
    resolveUpload: () => uploadResponseReady.resolve(),
    resolveSecondUpload: () => secondUploadResponseReady.resolve(),
    resolveFirstRunResponse: () => firstRunResponseReady.resolve(),
    uploadStarted: uploadStarted.promise,
    secondUploadStarted: secondUploadStarted.promise,
    runRequestStarted: runRequestStarted.promise,
    secondRunRequestStarted: secondRunRequestStarted.promise,
    firstRunResponsePulled: firstRunResponsePulled.promise,
    secondRunResponsePulled: secondRunResponsePulled.promise,
    runRequests,
    get threadCreateCount() {
      return threadCreateCount;
    },
  };
}

function renderThread(
  initialProps: HookProps,
  options: { strictMode?: boolean } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  queryClients.push(queryClient);

  const hook = renderHook(
    ({ threadId, displayThreadId, onStart }: HookProps) => {
      return useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        displayThreadId,
        isMock: true,
        onStart: (createdThreadId, runId) => {
          onStart({ viewThreadId: displayThreadId, createdThreadId, runId });
        },
        threadId,
      });
    },
    {
      initialProps,
      wrapper: createWrapper(queryClient, options.strictMode),
    },
  );

  return { ...hook, queryClient };
}

async function flushFrames() {
  for (let index = 0; index < 8; index += 1) {
    await act(async () => undefined);
  }
}

function messageWithFile() {
  return {
    text: "Summarize this file",
    files: [
      {
        type: "file" as const,
        url: "blob:brief",
        mediaType: "text/plain",
        filename: "brief.txt",
        file: new File(["hello"], "brief.txt", { type: "text/plain" }),
      },
    ],
  };
}

async function startPendingUpload({
  threadId,
  displayThreadId,
  sendThreadId,
  onStart,
}: HookProps & { sendThreadId: string }) {
  const fetchController = createFetchController();
  const hook = renderThread({ threadId, displayThreadId, onStart });
  await flushFrames();

  let submission: Promise<unknown> = Promise.resolve();
  act(() => {
    submission = hook.result.current.sendMessage(
      sendThreadId,
      messageWithFile(),
    );
  });
  await fetchController.uploadStarted;

  return { fetchController, hook, submission };
}

async function expectDroppedSubmission(
  fetchController: ReturnType<typeof createFetchController>,
  submission: Promise<unknown>,
) {
  let error: unknown;
  await act(async () => {
    fetchController.resolveUpload();
    try {
      await submission;
    } catch (caughtError) {
      error = caughtError;
    }
  });
  expect(error).toBeInstanceOf(Error);
  expect(error).toMatchObject({ message: "thread-submission-stale" });
}

afterEach(() => {
  cleanup();
  for (const queryClient of queryClients.splice(0)) {
    queryClient.clear();
  }
  window.fetch = originalWindowFetch;
  activeFetchImplementation = undefined;
  rs.unstubAllGlobals();
});

test("keeps an attachment send alive across a rerender of the same displayed thread", async () => {
  const starts: string[] = [];
  const initialStart = () => starts.push("initial");
  const latestStart = () => starts.push("latest");
  const { fetchController, hook, submission } = await startPendingUpload({
    threadId: "thread-a",
    displayThreadId: "thread-a",
    sendThreadId: "thread-a",
    onStart: initialStart,
  });

  await act(async () => {
    hook.rerender({
      threadId: "thread-a",
      displayThreadId: "thread-a",
      onStart: latestStart,
    });
  });
  expect(hook.result.current.isUploading).toBe(true);

  fetchController.resolveUpload();
  await act(async () => {
    await expect(submission).resolves.toBeUndefined();
  });

  expect(
    fetchController.runRequests.map((request) => request.threadId),
  ).toEqual(["thread-a"]);
  expect(starts).toEqual(["latest"]);
});

test("drops the upload continuation after navigating from A to B", async () => {
  const starts: StartEvent[] = [];
  const { fetchController, hook, submission } = await startPendingUpload({
    threadId: "thread-a",
    displayThreadId: "thread-a",
    sendThreadId: "thread-a",
    onStart: (event) => starts.push(event),
  });

  await act(async () => {
    hook.rerender({
      threadId: "thread-b",
      displayThreadId: "thread-b",
      onStart: (event) => starts.push(event),
    });
  });
  expect(hook.result.current.isUploading).toBe(false);

  await expectDroppedSubmission(fetchController, submission);

  expect(fetchController.runRequests).toEqual([]);
  expect(starts).toEqual([]);
});

test("drops an upload continuation after navigating A to B and back to A", async () => {
  const starts: StartEvent[] = [];
  const { fetchController, hook, submission } = await startPendingUpload({
    threadId: "thread-a",
    displayThreadId: "thread-a",
    sendThreadId: "thread-a",
    onStart: (event) => starts.push(event),
  });

  await act(async () => {
    hook.rerender({
      threadId: "thread-b",
      displayThreadId: "thread-b",
      onStart: (event) => starts.push(event),
    });
  });
  await act(async () => {
    hook.rerender({
      threadId: "thread-a",
      displayThreadId: "thread-a",
      onStart: (event) => starts.push(event),
    });
  });

  await expectDroppedSubmission(fetchController, submission);

  expect(fetchController.runRequests).toEqual([]);
  expect(starts).toEqual([]);
});

test("scopes a delayed run-created callback to its original view after A to B to A", async () => {
  const starts: string[] = [];
  const fetchController = createFetchController({ holdFirstRunResponse: true });
  const hook = renderThread({
    threadId: "thread-a",
    displayThreadId: "thread-a",
    onStart: () => starts.push("old A"),
  });
  await flushFrames();

  let oldSubmission: Promise<unknown> = Promise.resolve();
  act(() => {
    oldSubmission = hook.result.current.sendMessage(
      "thread-a",
      messageWithFile(),
    );
  });
  await act(async () => {
    await fetchController.uploadStarted;
    fetchController.resolveUpload();
    await fetchController.runRequestStarted;
  });
  expect(
    fetchController.runRequests.map((request) => request.threadId),
  ).toEqual(["thread-a"]);

  await act(async () => {
    hook.rerender({
      threadId: "thread-b",
      displayThreadId: "thread-b",
      onStart: () => starts.push("B"),
    });
  });
  await act(async () => {
    hook.rerender({
      threadId: "thread-a",
      displayThreadId: "thread-a",
      onStart: () => starts.push("latest A"),
    });
  });

  let newSubmission: Promise<unknown> = Promise.resolve();
  act(() => {
    newSubmission = hook.result.current.sendMessage(
      "thread-a",
      messageWithFile(),
    );
  });
  await act(async () => {
    await fetchController.secondUploadStarted;
  });
  expect(hook.result.current.isUploading).toBe(true);

  fetchController.resolveFirstRunResponse();
  await act(async () => {
    await fetchController.firstRunResponsePulled;
  });
  expect(starts).toEqual([]);
  expect(hook.result.current.isUploading).toBe(true);

  fetchController.resolveSecondUpload();
  await act(async () => {
    await fetchController.secondRunRequestStarted;
    await fetchController.secondRunResponsePulled;
  });
  await act(async () => {
    await Promise.all([oldSubmission, newSubmission]);
  });

  expect(starts).toEqual(["latest A"]);
  expect(
    fetchController.runRequests.map((request) => request.threadId),
  ).toEqual(["thread-a", "thread-a"]);
  hook.unmount();
});

test("an older upload cannot clear a newer thread's upload state or send lock", async () => {
  const starts: StartEvent[] = [];
  const oldSend = await startPendingUpload({
    threadId: "thread-a",
    displayThreadId: "thread-a",
    sendThreadId: "thread-a",
    onStart: (event) => starts.push(event),
  });

  await act(async () => {
    oldSend.hook.rerender({
      threadId: "thread-b",
      displayThreadId: "thread-b",
      onStart: (event) => starts.push(event),
    });
  });

  const newFetchController = createFetchController();
  let newSubmission: Promise<unknown> = Promise.resolve();
  act(() => {
    newSubmission = oldSend.hook.result.current.sendMessage(
      "thread-b",
      messageWithFile(),
    );
  });
  await newFetchController.uploadStarted;

  await expectDroppedSubmission(oldSend.fetchController, oldSend.submission);
  expect(oldSend.hook.result.current.isUploading).toBe(true);

  let duplicateSubmission: Promise<unknown> = Promise.resolve();
  act(() => {
    duplicateSubmission = oldSend.hook.result.current.sendMessage("thread-b", {
      text: "This duplicate must be dropped.",
      files: [],
    });
  });
  await expect(duplicateSubmission).resolves.toBeUndefined();
  expect(newFetchController.runRequests).toEqual([]);

  newFetchController.resolveUpload();
  await act(async () => {
    await expect(newSubmission).resolves.toBeUndefined();
  });

  expect(
    newFetchController.runRequests.map((request) => request.threadId),
  ).toEqual(["thread-b"]);
  expect(starts).toEqual([
    {
      viewThreadId: "thread-b",
      createdThreadId: "thread-b",
      runId: "run-1",
    },
  ]);
});

test("drops an upload continuation after its thread view unmounts", async () => {
  const starts: StartEvent[] = [];
  const { fetchController, hook, submission } = await startPendingUpload({
    threadId: "thread-a",
    displayThreadId: "thread-a",
    sendThreadId: "thread-a",
    onStart: (event) => starts.push(event),
  });

  await act(async () => {
    hook.unmount();
  });
  await expectDroppedSubmission(fetchController, submission);

  expect(fetchController.runRequests).toEqual([]);
  expect(starts).toEqual([]);
});

test("keeps an attachment send alive across StrictMode effect replay", async () => {
  const starts: string[] = [];
  const fetchController = createFetchController();
  const hook = renderThread(
    {
      threadId: "thread-a",
      displayThreadId: "thread-a",
      onStart: () => starts.push("strict"),
    },
    { strictMode: true },
  );
  await flushFrames();

  let submission: Promise<unknown> = Promise.resolve();
  act(() => {
    submission = hook.result.current.sendMessage("thread-a", messageWithFile());
  });
  await fetchController.uploadStarted;
  fetchController.resolveUpload();
  await act(async () => {
    await expect(submission).resolves.toBeUndefined();
    await fetchController.firstRunResponsePulled;
  });

  expect(
    fetchController.runRequests.map((request) => request.threadId),
  ).toEqual(["thread-a"]);
  expect(starts).toEqual(["strict"]);
  await act(async () => {
    hook.unmount();
  });
});

test("allows upload and run creation for a new thread with a stable display identity", async () => {
  const starts: StartEvent[] = [];
  const onStart = (event: StartEvent) => starts.push(event);
  const pending = await startPendingUpload({
    threadId: undefined,
    displayThreadId: "thread-new",
    sendThreadId: "thread-new",
    onStart,
  });
  const { fetchController, hook, submission } = pending;

  fetchController.resolveUpload();
  await act(async () => {
    await expect(submission).resolves.toBeUndefined();
  });
  await act(async () => {
    hook.rerender({
      threadId: "thread-new",
      displayThreadId: "thread-new",
      onStart,
    });
  });

  expect(fetchController.threadCreateCount).toBe(1);
  expect(
    fetchController.runRequests.map((request) => request.threadId),
  ).toEqual(["thread-new"]);
  expect(starts).toEqual([
    {
      viewThreadId: "thread-new",
      createdThreadId: "thread-new",
      runId: "run-1",
    },
  ]);
  hook.unmount();
});
