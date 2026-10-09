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
// references, staged files, the stored draft). It must not fire for a send
// whose attachments never upload, or a retry goes out without that context.

const mocks = rs.hoisted(() => ({
  events: [] as string[],
  submit: rs.fn(async () => undefined),
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

async function renderThreadStream() {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: false,
        threadId: "thread-1",
      }),
    {
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
  mocks.submit.mockReset();
  mocks.submit.mockImplementation(async () => {
    mocks.events.push("submit");
  });
});

afterEach(() => {
  rs.unstubAllGlobals();
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

test("reports the send after its attachments upload, right before the run is submitted", async () => {
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
  await act(async () => {
    await sendPromise;
  });

  expect(mocks.events).toEqual(["upload", "onSent", "submit"]);
  expect(onSent).toHaveBeenCalledTimes(1);
});

test("reports a text-only send before the run is submitted", async () => {
  stubUploadFetch(async () => {
    throw new Error("no upload expected");
  });
  const { result } = await renderThreadStream();
  const onSent = rs.fn(() => {
    mocks.events.push("onSent");
  });

  await act(async () => {
    await result.current.sendMessage(
      "thread-1",
      { text: "Hello", files: [] },
      undefined,
      { onSent },
    );
  });

  expect(mocks.events).toEqual(["onSent", "submit"]);
});
