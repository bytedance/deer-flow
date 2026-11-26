import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  createHitlApprovalResponses,
  type HitlApprovalRequest,
  type HitlApprovalResponse,
} from "@/core/messages/human-input";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

const mocks = rs.hoisted(() => ({
  isLoading: false,
  interrupt: undefined as unknown,
  toastError: rs.fn(),
  submit: rs.fn(
    async (_input: unknown, _options?: Record<string, unknown>) => undefined,
  ),
  stop: rs.fn(async () => undefined),
  useStreamOptions: undefined as unknown,
}));

const request: HitlApprovalRequest = {
  version: 1,
  kind: "hitl_approval",
  request_id: "hitl_approval:ai-1:call-1",
  actions: [
    {
      tool_call_id: "call-1",
      tool_name: "write_file",
      args_summary: JSON.stringify({ path: "/tmp/a.txt" }),
      request_id: "hitl_approval:ai-1:call-1",
    },
  ],
  allowed_decisions: ["approve", "reject"],
  pending_tool_call_ids: ["call-1"],
};

const secondRequest: HitlApprovalRequest = {
  ...request,
  request_id: "hitl_approval:ai-1:call-2",
  actions: [
    {
      ...request.actions[0]!,
      tool_call_id: "call-2",
      request_id: "hitl_approval:ai-1:call-2",
    },
  ],
  pending_tool_call_ids: ["call-2"],
};

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: unknown) => {
    mocks.useStreamOptions = options;
    return {
      assistantId: "custom-agent",
      error: undefined,
      getMessagesMetadata: () => undefined,
      history: [{ next: ["tools"] }],
      interrupt: mocks.interrupt,
      isLoading: mocks.isLoading,
      isThreadLoading: false,
      messages: [],
      stop: mocks.stop,
      submit: mocks.submit,
      values: { artifacts: [], messages: [], title: "", todos: [] },
    };
  },
}));

rs.mock("sonner", () => ({
  toast: Object.assign(rs.fn(), {
    error: mocks.toastError,
    warning: rs.fn(),
  }),
}));

function streamCallbacks() {
  return mocks.useStreamOptions as {
    onCreated: (meta: { thread_id: string; run_id: string }) => void;
    onError: (error: unknown) => void;
    onFinish: (
      state: { values: Record<string, unknown> },
      run?: { run_id: string },
    ) => void;
  };
}

function wrapper({ children }: { children: ReactNode }) {
  return createElement(
    QueryClientProvider,
    {
      client: new QueryClient({
        defaultOptions: { queries: { retry: false } },
      }),
    },
    createElement(
      I18nContext.Provider,
      {
        value: { locale: "en-US", setLocale: () => undefined, t: enUS },
      },
      children,
    ),
  );
}

beforeEach(() => {
  mocks.isLoading = false;
  mocks.interrupt = { value: request };
  mocks.toastError.mockReset();
  mocks.submit.mockReset();
  mocks.stop.mockReset();
  mocks.stop.mockResolvedValue(undefined);
  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({ thread_id: "thread-1", run_id: "run-1" });
  });
  rs.stubGlobal("fetch", async (input: unknown) => {
    const url = String(input);
    if (url.includes("/messages/page")) {
      return new Response(
        JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.includes("/runs")) {
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.unstubAllGlobals();
});

test("resume keeps paused send context, clears stale pending state, and never submits while streaming", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        assistantId: "custom-agent",
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);

  await act(async () => {
    await rendered.result.current.sendMessage(
      "thread-1",
      { text: "write a file", files: [] },
      { model_name: "paused-model" },
      { conversationReferences: ["authorized-thread"] },
    );
  });
  const responses = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })!;

  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        responses,
      ),
    ).toBe(true);
  });

  expect(mocks.submit).toHaveBeenCalledTimes(2);
  const [input, options] = mocks.submit.mock.calls[1]!;
  expect(input).toBeNull();
  expect(options).toMatchObject({
    checkpoint: null,
    streamResumable: true,
    streamMode: ["values"],
    config: { recursion_limit: 1000 },
    context: {
      model_name: "paused-model",
      conversation_references: ["authorized-thread"],
    },
  });
  expect("streamSubgraphs" in options!).toBe(false);
  expect(rendered.result.current.hasPendingApproval).toBe(false);
  expect(rendered.result.current.approvalRequests).toEqual([]);
  expect(mocks.useStreamOptions).toMatchObject({ assistantId: "custom-agent" });

  mocks.isLoading = true;
  rendered.rerender();
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        responses,
      ),
    ).toBe(false);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(2);
});

test("queued resume stays pending until accepted and guards duplicate submits", async () => {
  mocks.submit.mockImplementation(async () => undefined);
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "reject",
  })!;

  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      responses,
    );
  });
  await act(async () => undefined);
  expect(rendered.result.current.hasPendingApproval).toBe(true);
  expect(rendered.result.current.approvalRequests).toEqual([request]);
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        responses,
      ),
    ).toBe(false);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(1);

  await act(async () => {
    streamCallbacks().onCreated({ thread_id: "thread-1", run_id: "run-2" });
    expect(await submission).toBe(true);
  });
  expect(rendered.result.current.hasPendingApproval).toBe(false);
});

test("stream rejection keeps the approval open and returns failure", async () => {
  mocks.submit.mockImplementation(async () => undefined);
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })!;

  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      responses,
    );
  });
  await act(async () => undefined);
  expect(rendered.result.current.hasPendingApproval).toBe(true);

  await act(async () => {
    streamCallbacks().onError(new Error("Gateway returned 409"));
    expect(await submission).toBe(false);
  });
  expect(rendered.result.current.hasPendingApproval).toBe(true);
  expect(rendered.result.current.approvalRequests).toEqual([request]);
});

test("stream errors show friendly approval messages from Error instances", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);

  const cases = [
    ["hitl_approval_disabled", enUS.humanInput.approval.featureDisabled],
    ["no_pending_approval", enUS.humanInput.approval.noPending],
  ] as const;
  for (const [code, message] of cases) {
    await act(async () => {
      streamCallbacks().onError(new Error(`Gateway rejected resume: ${code}`));
    });
    expect(mocks.toastError).toHaveBeenLastCalledWith(message);
  }
});

test("submit rejections show friendly approval messages from Error instances", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })!;
  const cases = [
    ["hitl_approval_disabled", enUS.humanInput.approval.featureDisabled],
    ["no_pending_approval", enUS.humanInput.approval.noPending],
  ] as const;

  for (const [code, message] of cases) {
    mocks.submit.mockRejectedValueOnce(new Error(`Resume failed: ${code}`));
    await act(async () => {
      expect(
        await rendered.result.current.submitHitlApproval(
          "thread-1",
          request,
          responses,
        ),
      ).toBe(false);
    });
    expect(mocks.toastError).toHaveBeenLastCalledWith(message);
  }
});

test("stream errors preserve answered history while another failed submission stays pending", async () => {
  mocks.interrupt = { value: [secondRequest] };
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);

  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        createHitlApprovalResponses(request, { "call-1": "approve" })!,
      ),
    ).toBe(true);
  });
  expect(rendered.result.current.approvalRequests).toEqual([secondRequest]);

  mocks.submit.mockImplementation(async () => undefined);
  let failedSubmission!: Promise<boolean>;
  act(() => {
    failedSubmission = rendered.result.current.submitHitlApproval(
      "thread-1",
      secondRequest,
      createHitlApprovalResponses(secondRequest, { "call-2": "reject" })!,
    );
  });
  await act(async () => undefined);
  await act(async () => {
    streamCallbacks().onError(new Error("stream failed"));
    expect(await failedSubmission).toBe(false);
  });

  expect(rendered.result.current.approvalRequests).toEqual([secondRequest]);
  expect(rendered.result.current.hasPendingApproval).toBe(true);
});

test("a replay error reopens an accepted approval that is still actionable", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);

  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        createHitlApprovalResponses(request, { "call-1": "approve" })!,
      ),
    ).toBe(true);
  });
  expect(rendered.result.current.approvalRequests).toEqual([]);

  await act(async () => {
    streamCallbacks().onError(new Error("replay failed"));
  });
  expect(rendered.result.current.approvalRequests).toEqual([request]);
  expect(rendered.result.current.hasPendingApproval).toBe(true);

  await act(async () => {
    streamCallbacks().onError(new Error("replay failed again"));
  });
  expect(rendered.result.current.approvalRequests).toEqual([request]);
  expect(rendered.result.current.hasPendingApproval).toBe(true);
});

test("a replay error reopens an accepted approval still pending in REST metadata", async () => {
  mocks.interrupt = undefined;
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
        restInterrupts: { value: request },
      }),
    { wrapper },
  );
  await act(async () => undefined);

  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        createHitlApprovalResponses(request, { "call-1": "approve" })!,
      ),
    ).toBe(true);
  });
  expect(rendered.result.current.approvalRequests).toEqual([]);

  await act(async () => {
    streamCallbacks().onError(new Error("replay failed"));
  });
  expect(rendered.result.current.approvalRequests).toEqual([request]);
  expect(rendered.result.current.hasPendingApproval).toBe(true);
});

test("a replay error preserves answers no longer present in live or REST interrupts", async () => {
  mocks.interrupt = { value: [request, secondRequest] };
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);

  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        createHitlApprovalResponses(request, { "call-1": "approve" })!,
      ),
    ).toBe(true);
  });
  mocks.interrupt = { value: secondRequest };
  rendered.rerender();
  await act(async () => {
    streamCallbacks().onError(new Error("replay failed"));
  });

  expect(rendered.result.current.approvalRequests).toEqual([secondRequest]);
});

test("rejects duplicate, extra, and foreign response identifiers before dispatch", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const response = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })![0]!;
  const foreign = {
    ...response,
    request_id: "hitl_approval:ai-1:foreign",
    tool_call_id: "foreign",
  };
  const invalidBatches: HitlApprovalResponse[][] = [
    [response, response],
    [response, foreign],
    [foreign],
    [{ ...response, request_id: "hitl_approval:ai-1:foreign" }],
  ];

  for (const responses of invalidBatches) {
    await act(async () => {
      expect(
        await rendered.result.current.submitHitlApproval(
          "thread-1",
          request,
          responses,
        ),
      ).toBe(false);
    });
  }
  expect(mocks.submit).not.toHaveBeenCalled();
});

test("abort resolves the pending approval and permits an immediate retry", async () => {
  mocks.submit.mockImplementation(async () => undefined);
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })!;
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      responses,
    );
  });
  await act(async () => undefined);

  await act(async () => {
    await rendered.result.current.thread.stop();
    expect(await submission).toBe(false);
  });
  expect(mocks.stop).toHaveBeenCalledTimes(1);
  expect(rendered.result.current.hasPendingApproval).toBe(true);

  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({ thread_id: "thread-1", run_id: "run-retry" });
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        responses,
      ),
    ).toBe(true);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(2);
});

test("finish without creation resolves failure and unlocks another submission", async () => {
  mocks.submit.mockImplementation(async () => undefined);
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "reject",
  })!;
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      responses,
    );
  });
  await act(async () => undefined);

  await act(async () => {
    streamCallbacks().onFinish({ values: {} });
    expect(await submission).toBe(false);
  });
  expect(rendered.result.current.hasPendingApproval).toBe(true);

  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({ thread_id: "thread-1", run_id: "run-retry" });
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        responses,
      ),
    ).toBe(true);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(2);
});

test("a stalled acceptance times out and permits a fresh submission", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.submit.mockImplementation(async () => undefined);
  const { HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS, useThreadStream } =
    await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })!;
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      responses,
    );
  });
  await act(async () => undefined);

  await act(async () => {
    await rs.advanceTimersByTimeAsync(HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS);
    expect(await submission).toBe(false);
  });
  expect(rendered.result.current.hasPendingApproval).toBe(true);

  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({ thread_id: "thread-1", run_id: "run-retry" });
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        responses,
      ),
    ).toBe(true);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(2);
});

test("late creation after the acceptance deadline clears the stale approval", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.submit.mockImplementation(async () => undefined);
  const { HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS, useThreadStream } =
    await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })!;
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      responses,
    );
  });
  await act(async () => undefined);

  await act(async () => {
    await rs.advanceTimersByTimeAsync(HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS);
    expect(await submission).toBe(false);
  });
  expect(rendered.result.current.approvalRequests).toEqual([request]);

  await act(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-1",
      run_id: "run-late-acceptance",
    });
  });
  expect(rendered.result.current.approvalRequests).toEqual([]);
  expect(rendered.result.current.hasPendingApproval).toBe(false);
});

test("late creation resolves a timed-out request before a different retry", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.interrupt = { value: [request, secondRequest] };
  mocks.submit.mockImplementation(async () => undefined);
  const { HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS, useThreadStream } =
    await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  let firstSubmission!: Promise<boolean>;
  act(() => {
    firstSubmission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      createHitlApprovalResponses(request, { "call-1": "approve" })!,
    );
  });
  await act(async () => {
    await rs.advanceTimersByTimeAsync(HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS);
    expect(await firstSubmission).toBe(false);
  });

  const secondResponses = createHitlApprovalResponses(secondRequest, {
    "call-2": "reject",
  })!;
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        secondRequest,
        secondResponses,
      ),
    ).toBe(false);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(1);
  expect(mocks.stop).toHaveBeenCalledTimes(1);

  await act(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-1",
      run_id: "run-late-old-request",
    });
  });
  expect(rendered.result.current.approvalRequests).toEqual([secondRequest]);

  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-1",
      run_id: "run-current-request",
    });
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        secondRequest,
        secondResponses,
      ),
    ).toBe(true);
  });
  expect(rendered.result.current.approvalRequests).toEqual([]);
});

test("a different retry waits for metadata when the timed-out request never emits", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.interrupt = { value: [request, secondRequest] };
  mocks.submit.mockImplementation(async () => undefined);
  const { HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS, useThreadStream } =
    await import("@/core/threads/hooks");
  const rendered = renderHook(
    ({ restInterrupts, restInterruptsLoading }) =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
        restInterrupts,
        restInterruptsLoading,
      }),
    {
      initialProps: {
        restInterrupts: { value: [request, secondRequest] },
        restInterruptsLoading: false,
      },
      wrapper,
    },
  );
  await act(async () => undefined);
  let firstSubmission!: Promise<boolean>;
  act(() => {
    firstSubmission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      createHitlApprovalResponses(request, { "call-1": "approve" })!,
    );
  });
  await act(async () => {
    await rs.advanceTimersByTimeAsync(HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS);
    expect(await firstSubmission).toBe(false);
  });

  const secondResponses = createHitlApprovalResponses(secondRequest, {
    "call-2": "reject",
  })!;
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        secondRequest,
        secondResponses,
      ),
    ).toBe(false);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(1);
  expect(mocks.stop).toHaveBeenCalledTimes(1);

  rendered.rerender({
    restInterrupts: { value: [secondRequest] },
    restInterruptsLoading: true,
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        secondRequest,
        secondResponses,
      ),
    ).toBe(false);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(1);
  expect(mocks.stop).toHaveBeenCalledTimes(1);

  rendered.rerender({
    restInterrupts: { value: [secondRequest] },
    restInterruptsLoading: false,
  });
  await act(async () => undefined);
  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-1",
      run_id: "run-after-metadata-resolution",
    });
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        secondRequest,
        secondResponses,
      ),
    ).toBe(true);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(2);
  expect(mocks.stop).toHaveBeenCalledTimes(1);
});

test("unmount cancels late timeout reconciliation", async () => {
  mocks.submit.mockImplementation(async () => undefined);
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      createHitlApprovalResponses(request, { "call-1": "approve" })!,
    );
  });

  rendered.unmount();
  await act(async () => {
    expect(await submission).toBe(false);
  });
  await act(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-1",
      run_id: "run-after-unmount",
    });
  });
  expect(rendered.result.current.approvalRequests).toEqual([request]);
  expect(rendered.result.current.hasPendingApproval).toBe(true);
});

test("an error cancels late timeout reconciliation", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.submit.mockImplementation(async () => undefined);
  const { HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS, useThreadStream } =
    await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId: "thread-1",
      }),
    { wrapper },
  );
  await act(async () => undefined);
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      createHitlApprovalResponses(request, { "call-1": "approve" })!,
    );
  });
  await act(async () => {
    await rs.advanceTimersByTimeAsync(HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS);
    expect(await submission).toBe(false);
    streamCallbacks().onError(new Error("resume failed"));
  });

  await act(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-1",
      run_id: "run-after-error",
    });
  });
  expect(rendered.result.current.approvalRequests).toEqual([request]);
  expect(rendered.result.current.hasPendingApproval).toBe(true);
});

test("thread switching cancels late timeout reconciliation", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.submit.mockImplementation(async () => undefined);
  const { HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS, useThreadStream } =
    await import("@/core/threads/hooks");
  const rendered = renderHook(
    ({ threadId }) =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId,
      }),
    { initialProps: { threadId: "thread-1" }, wrapper },
  );
  await act(async () => undefined);
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      createHitlApprovalResponses(request, { "call-1": "approve" })!,
    );
  });
  await act(async () => {
    await rs.advanceTimersByTimeAsync(HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS);
    expect(await submission).toBe(false);
  });

  rendered.rerender({ threadId: "thread-2" });
  await act(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-1",
      run_id: "run-after-switch",
    });
  });
  rendered.rerender({ threadId: "thread-1" });
  await act(async () => undefined);

  expect(rendered.result.current.approvalRequests).toEqual([request]);
  expect(rendered.result.current.hasPendingApproval).toBe(true);
});

test("a never-settling submit is stopped on timeout and supports retry and thread switching", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const { HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS, useThreadStream } =
    await import("@/core/threads/hooks");
  const rendered = renderHook(
    ({ threadId }) =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        threadId,
      }),
    { initialProps: { threadId: "thread-1" }, wrapper },
  );
  mocks.submit.mockImplementation(() => {
    // The SDK enters its real loading state as soon as the resume is queued.
    mocks.isLoading = true;
    rendered.rerender({ threadId: "thread-1" });
    return new Promise<undefined>(() => undefined);
  });
  mocks.stop.mockImplementation(async () => {
    mocks.isLoading = false;
    rendered.rerender({ threadId: "thread-1" });
  });
  await act(async () => undefined);
  const responses = createHitlApprovalResponses(request, {
    "call-1": "approve",
  })!;
  let submission!: Promise<boolean>;
  act(() => {
    submission = rendered.result.current.submitHitlApproval(
      "thread-1",
      request,
      responses,
    );
  });
  await act(async () => undefined);
  expect(rendered.result.current.thread.isLoading).toBe(true);

  await act(async () => {
    await rs.advanceTimersByTimeAsync(HITL_APPROVAL_ACCEPTANCE_TIMEOUT_MS);
    expect(await submission).toBe(false);
  });
  expect(mocks.stop).toHaveBeenCalledTimes(1);
  expect(mocks.toastError).toHaveBeenCalledWith(
    enUS.humanInput.approval.submitTimeout,
  );
  expect(rendered.result.current.thread.isLoading).toBe(false);
  expect(rendered.result.current.hasPendingApproval).toBe(true);

  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({ thread_id: "thread-1", run_id: "run-retry" });
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-1",
        request,
        responses,
      ),
    ).toBe(true);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(2);

  rendered.rerender({ threadId: "thread-2" });
  await act(async () => undefined);
  mocks.submit.mockImplementation(async () => {
    streamCallbacks().onCreated({
      thread_id: "thread-2",
      run_id: "run-after-switch",
    });
  });
  await act(async () => {
    expect(
      await rendered.result.current.submitHitlApproval(
        "thread-2",
        request,
        responses,
      ),
    ).toBe(true);
  });
  expect(mocks.submit).toHaveBeenCalledTimes(3);
});
