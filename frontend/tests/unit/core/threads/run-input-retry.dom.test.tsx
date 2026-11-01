import type { Run } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { AuthQueryScopeContext } from "@/core/auth/query-scope";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { useThreadStream } from "@/core/threads/hooks";
import {
  runInputsKey,
  type RunInput,
  type RunInputMode,
} from "@/core/threads/run-inputs";

const streamMockState = rs.hoisted(() => ({
  joinStream: rs.fn(async () => undefined),
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    runs: { list: async () => [] as Run[] },
  }),
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: () => ({
    isLoading: true,
    joinStream: streamMockState.joinStream,
    messages: [],
    stop: async () => undefined,
    submit: async () => undefined,
    values: { artifacts: [], messages: [], title: "", todos: [] },
  }),
}));

type SubmittedInput = {
  runId: string;
  body: {
    request_id: string;
    text: string;
    mode: RunInputMode;
    context: Record<string, unknown>;
  };
};

const queryClients: QueryClient[] = [];
let activeRunId: string;
let receipts: RunInput[];
let submittedInputs: SubmittedInput[];
let firstPostFailure:
  | "conflict"
  | "network"
  | "server"
  | "malformed"
  | "accepted";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function receiptFor({ runId, body }: SubmittedInput): RunInput {
  return {
    id: body.request_id,
    target_run_id: runId,
    message_id: `message-${body.request_id}`,
    text: body.text,
    mode: body.mode,
    status: "pending",
    created_at: "2026-11-02T00:00:00Z",
  };
}

function createWrapper(queryClient: QueryClient) {
  return function RunInputRetryTestWrapper({
    children,
  }: {
    children: ReactNode;
  }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        AuthQueryScopeContext.Provider,
        { value: "account-1" },
        createElement(
          I18nContext.Provider,
          {
            value: {
              locale: "en-US",
              setLocale: () => undefined,
              t: enUS,
            },
          },
          children,
        ),
      ),
    );
  };
}

async function flushFrames() {
  for (let index = 0; index < 8; index += 1) {
    await act(async () => {
      await rs.advanceTimersByTimeAsync(1);
    });
  }
}

async function renderThread() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClients.push(queryClient);
  const rendered = renderHook(
    ({ modelName }: { modelName: string }) =>
      useThreadStream({
        context: {
          ...DEFAULT_LOCAL_SETTINGS.context,
          model_name: modelName,
        },
        threadId: "thread-1",
      }),
    {
      initialProps: { modelName: "model-original" },
      wrapper: createWrapper(queryClient),
    },
  );
  await flushFrames();
  expect(rendered.result.current.canSendInput).toBe(true);
  expect(rendered.result.current.activeRunId).toBe("run-1");
  return { queryClient, ...rendered };
}

async function advanceToNextRun(queryClient: QueryClient) {
  activeRunId = "run-2";
  await act(async () => {
    await queryClient.invalidateQueries({
      queryKey: runInputsKey("thread-1"),
    });
  });
  await flushFrames();
}

beforeEach(() => {
  rs.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"],
  });
  window.sessionStorage.clear();
  activeRunId = "run-1";
  receipts = [];
  submittedInputs = [];
  firstPostFailure = "conflict";
  rs.stubGlobal(
    "fetch",
    rs.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        "http://localhost",
      );
      if (url.pathname === "/api/features") {
        return jsonResponse({ run_inputs: true });
      }
      if (url.pathname === "/api/threads/thread-1/messages/page") {
        return jsonResponse({
          data: [],
          has_more: false,
          next_before_seq: null,
        });
      }
      if (url.pathname === "/api/threads/thread-1/inputs") {
        return jsonResponse({ items: receipts, active_run_id: activeRunId });
      }
      const match = /^\/api\/threads\/thread-1\/runs\/([^/]+)\/inputs$/.exec(
        url.pathname,
      );
      if (match && init?.method === "POST") {
        expect(init.credentials).toBe("include");
        if (typeof init.body !== "string") {
          throw new Error("Expected a JSON run-input request body");
        }
        const submission: SubmittedInput = {
          runId: match[1]!,
          body: JSON.parse(init.body) as SubmittedInput["body"],
        };
        submittedInputs.push(submission);
        const receipt = receiptFor(submission);
        if (submittedInputs.length === 1) {
          if (firstPostFailure === "conflict") {
            return jsonResponse(
              {
                detail:
                  "Run is finishing or stopped; this input was not accepted",
              },
              409,
            );
          }
          if (firstPostFailure === "server") {
            return jsonResponse({ detail: "Gateway unavailable" }, 500);
          }
          if (firstPostFailure === "malformed") {
            return new Response("{", {
              status: 200,
              headers: { "Content-Type": "application/json" },
            });
          }
          if (firstPostFailure === "accepted") {
            receipts.push(receipt);
          }
          throw new TypeError("Failed to fetch");
        }
        receipts.push(receipt);
        return jsonResponse(receipt);
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    }),
  );
});

afterEach(() => {
  cleanup();
  for (const queryClient of queryClients.splice(0)) {
    queryClient.clear();
  }
  rs.useRealTimers();
  rs.unstubAllGlobals();
});

test.each(["queue", "steer"] as const)(
  "sends a rejected %s input to the next active run with a new request ID",
  async (mode) => {
    const { result, queryClient } = await renderThread();

    await act(async () => {
      await expect(result.current.sendInput("Continue", mode)).rejects.toThrow(
        "Run is finishing or stopped; this input was not accepted",
      );
    });
    expect(submittedInputs).toHaveLength(1);
    expect(receipts).toEqual([]);

    await advanceToNextRun(queryClient);
    expect(result.current.activeRunId).toBe("run-2");
    await act(async () => {
      await result.current.sendInput("Continue", mode);
    });

    expect(submittedInputs).toHaveLength(2);
    expect(submittedInputs[1]?.runId).toBe("run-2");
    expect(submittedInputs[1]?.body.request_id).not.toBe(
      submittedInputs[0]?.body.request_id,
    );
  },
);

test.each(["network", "server", "malformed"] as const)(
  "keeps the original run, request ID and context after an uncertain %s failure",
  async (failure) => {
    firstPostFailure = failure;
    const { result, queryClient, rerender } = await renderThread();

    await act(async () => {
      await expect(
        result.current.sendInput("Continue", "queue"),
      ).rejects.toThrow();
    });
    expect(receipts).toEqual([]);
    const first = submittedInputs[0]!;
    expect(first.body.context.model_name).toBe("model-original");

    await advanceToNextRun(queryClient);
    rerender({ modelName: "model-new" });
    expect(result.current.activeRunId).toBe("run-2");
    await act(async () => {
      await result.current.sendInput("Continue", "queue");
    });

    expect(submittedInputs).toHaveLength(2);
    expect(submittedInputs[1]).toEqual(first);
  },
);

test("recovers an accepted input when the POST response was lost", async () => {
  firstPostFailure = "accepted";
  const { result } = await renderThread();

  await act(async () => {
    await expect(
      result.current.sendInput("Continue", "queue"),
    ).resolves.toEqual(
      expect.objectContaining({
        target_run_id: "run-1",
        text: "Continue",
        mode: "queue",
        status: "pending",
      }),
    );
  });

  expect(submittedInputs).toHaveLength(1);
  expect(receipts[0]?.id).toBe(submittedInputs[0]?.body.request_id);
});
