import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import {
  buildConversationReferenceMetadata,
  readConversationReferences,
} from "@/core/conversation-references";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { FileInMessage } from "@/core/messages/utils";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import {
  buildReferenceMessageMetadata,
  readReferenceMessageContexts,
} from "@/core/sidecar/reference-metadata";
import type { UploadResponse } from "@/core/uploads/api";

const streamMockState = rs.hoisted(() => ({
  submit: rs.fn(async () => undefined),
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: () => ({
    isLoading: false,
    messages: [],
    stop: rs.fn(async () => undefined),
    submit: streamMockState.submit,
    values: { artifacts: [], messages: [], title: "", todos: [] },
  }),
}));

const QUOTE = {
  type: "referenced_message" as const,
  label: "Earlier answer",
  messageId: "ai-1",
  role: "assistant" as const,
  content: "The quoted text",
};
const CONVERSATION_REFERENCE = {
  threadId: "thread-other",
  title: "Another conversation",
};
const STAGED_FILE: FileInMessage = {
  filename: "brief.md",
  size: 12,
  path: "/mnt/user-data/uploads/brief.md",
  status: "uploaded",
};
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

/**
 * Hold the upload POST open until the test resolves it, so the optimistic
 * bubble can be observed both while uploading and after the upload lands.
 */
function stubDeferredUploadFetch() {
  let resolveUpload: (() => void) | undefined;
  const uploadResponded = new Promise<void>((resolve) => {
    resolveUpload = resolve;
  });
  rs.stubGlobal("fetch", async (input: unknown) => {
    const url = String(input);
    if (/\/api\/threads\/[^/]+\/uploads$/.test(url)) {
      await uploadResponded;
      return new Response(JSON.stringify(UPLOAD_RESPONSE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (/\/api\/threads\/[^/]+\/messages\/page/.test(url)) {
      return new Response(
        JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  return () => resolveUpload?.();
}

function createWrapper(queryClient: QueryClient) {
  return function ThreadStreamTestWrapper({
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

function displayedHuman(messages: Message[]): Message | undefined {
  return messages.filter((message) => message.type === "human").at(-1);
}

beforeEach(() => {
  streamMockState.submit.mockClear();
});

afterEach(() => {
  rs.unstubAllGlobals();
});

test("keeps quote and conversation reference chips on the optimistic bubble through the upload", async () => {
  const resolveUpload = stubDeferredUploadFetch();
  const { useThreadStream } = await import("@/core/threads/hooks");
  const { result } = renderHook(
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

  let sendPromise: Promise<unknown> | undefined;
  act(() => {
    sendPromise = result.current.sendMessage(
      "thread-1",
      {
        text: "Compare these",
        files: [
          {
            type: "file",
            url: "blob:report",
            mediaType: "application/pdf",
            filename: "report.pdf",
            file: new File(["%PDF"], "report.pdf", {
              type: "application/pdf",
            }),
          },
        ],
      },
      undefined,
      {
        additionalKwargs: {
          ...buildReferenceMessageMetadata([QUOTE]),
          ...buildConversationReferenceMetadata([CONVERSATION_REFERENCE]),
          files: [STAGED_FILE],
        },
      },
    );
  });
  await flushFrames();

  const uploading = displayedHuman(result.current.thread.messages);
  expect(readReferenceMessageContexts(uploading?.additional_kwargs)).toEqual([
    QUOTE,
  ]);
  expect(readConversationReferences(uploading?.additional_kwargs)).toEqual([
    CONVERSATION_REFERENCE,
  ]);
  expect(uploading?.additional_kwargs?.files).toEqual([
    STAGED_FILE,
    { filename: "report.pdf", size: 0, status: "uploading" },
  ]);

  resolveUpload();
  await act(async () => {
    await sendPromise;
  });

  // The server has not echoed the human yet, so the optimistic copy is
  // still the bubble on screen.
  const uploaded = displayedHuman(result.current.thread.messages);
  const submitCalls = streamMockState.submit.mock.calls as unknown as Array<
    [{ messages: Message[] }]
  >;
  const submitted = submitCalls.at(-1)?.[0].messages.at(-1);
  expect(uploaded?.id).toBe(submitted?.id);
  expect(uploaded?.additional_kwargs).toEqual(submitted?.additional_kwargs);
  expect(readReferenceMessageContexts(uploaded?.additional_kwargs)).toEqual([
    QUOTE,
  ]);
  expect(readConversationReferences(uploaded?.additional_kwargs)).toEqual([
    CONVERSATION_REFERENCE,
  ]);
  expect(uploaded?.additional_kwargs?.files).toEqual([
    STAGED_FILE,
    {
      filename: "report.pdf",
      size: 42,
      path: "/mnt/user-data/uploads/report.pdf",
      status: "uploaded",
    },
  ]);
});
