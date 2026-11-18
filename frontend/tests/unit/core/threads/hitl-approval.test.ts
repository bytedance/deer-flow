import { describe, expect, it } from "@rstest/core";

import {
  createHitlApprovalResponses,
  extractHitlApprovalRequests,
  parseApprovalArgsSummary,
  parseHitlApprovalRequest,
  type HitlApprovalRequest,
} from "@/core/messages/human-input";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import {
  buildHitlApprovalSubmitOptions,
  deriveHitlApprovalState,
  THREAD_RUN_RECURSION_LIMIT,
} from "@/core/threads/hooks";

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
    {
      tool_call_id: "call-2",
      tool_name: "bash",
      args_summary: JSON.stringify({ command: "pwd" }),
      request_id: "hitl_approval:ai-1:call-2",
    },
  ],
  allowed_decisions: ["approve", "reject"],
  pending_tool_call_ids: ["call-1", "call-2"],
};

describe("parseHitlApprovalRequest", () => {
  it.each([
    null,
    { ...request, kind: "human_input_request" },
    { ...request, version: 2 },
    { ...request, request_id: " " },
    { ...request, actions: [], pending_tool_call_ids: [] },
    { ...request, allowed_decisions: ["approve", "approve"] },
    { ...request, allowed_decisions: ["maybe"] },
    {
      ...request,
      actions: [request.actions[0], request.actions[0]],
    },
    {
      ...request,
      actions: [
        request.actions[0],
        { ...request.actions[1], tool_call_id: "call-1" },
      ],
    },
    {
      ...request,
      actions: [
        request.actions[0],
        { ...request.actions[1], args_summary: null },
      ],
    },
    { ...request, pending_tool_call_ids: ["call-1", "missing"] },
    { ...request, pending_tool_call_ids: ["call-1", "call-1"] },
  ])("rejects malformed request %#", (value) => {
    expect(parseHitlApprovalRequest(value)).toBeNull();
  });
});

describe("HITL approval interrupt state", () => {
  it("filters static breakpoints and locks the reload window by default", () => {
    expect(extractHitlApprovalRequests({ when: "breakpoint" })).toEqual([]);
    const loading = deriveHitlApprovalState({
      liveInterrupt: { when: "breakpoint" },
      historyLoading: true,
      next: ["HitlApprovalMiddleware.after_model"],
      answeredRequestIds: new Set(),
    });
    expect(loading.requests).toEqual([]);
    expect(loading.hasPendingApproval).toBe(true);

    const loaded = deriveHitlApprovalState({
      liveInterrupt: { when: "breakpoint" },
      historyLoading: false,
      next: ["tools"],
      answeredRequestIds: new Set(),
    });
    expect(loaded.requests).toEqual([]);
    expect(loaded.hasPendingApproval).toBe(false);
  });

  it("stays locked when approval metadata fails for a paused snapshot", () => {
    const failed = deriveHitlApprovalState({
      liveInterrupt: undefined,
      restInterrupts: undefined,
      restInterruptsError: true,
      historyLoading: false,
      next: ["HitlApprovalMiddleware.after_model"],
      answeredRequestIds: new Set(),
    });
    expect(failed.requests).toEqual([]);
    expect(failed.hasPendingApproval).toBe(true);

    const notPaused = deriveHitlApprovalState({
      liveInterrupt: undefined,
      restInterruptsError: true,
      historyLoading: false,
      next: ["tools"],
      answeredRequestIds: new Set(),
    });
    expect(notPaused.hasPendingApproval).toBe(false);
  });

  it("does not show approval waiting for clarification-only history loading", () => {
    const loading = deriveHitlApprovalState({
      liveInterrupt: undefined,
      historyLoading: true,
      next: ["ask_clarification"],
      answeredRequestIds: new Set(),
    });
    expect(loading.requests).toEqual([]);
    expect(loading.hasPendingApproval).toBe(false);
  });

  it("reads live and REST interrupt shapes and honors local answered state", () => {
    const live = deriveHitlApprovalState({
      liveInterrupt: { id: "task-local-id", value: request },
      historyLoading: false,
      next: ["tools"],
      answeredRequestIds: new Set(),
    });
    expect(live.requests).toEqual([request]);
    expect(live.hasPendingApproval).toBe(true);

    const rest = deriveHitlApprovalState({
      liveInterrupt: undefined,
      restInterrupts: { "task-id": [{ id: "interrupt-id", value: request }] },
      historyLoading: false,
      next: ["tools"],
      answeredRequestIds: new Set([request.request_id]),
    });
    expect(rest.requests).toEqual([]);
    expect(rest.hasPendingApproval).toBe(false);
  });

  it("parses the backend's Python-repr string map without truncating replacements", () => {
    expect(
      parseApprovalArgsSummary(
        String.raw`{'path': '/tmp/a.txt', 'old_str': 'old\nsecond', 'new_str': "it's new"}`,
      ),
    ).toEqual({
      path: "/tmp/a.txt",
      old_str: "old\nsecond",
      new_str: "it's new",
    });
  });

  it("refuses to construct a partial response batch", () => {
    expect(
      createHitlApprovalResponses(request, { "call-1": "approve" }),
    ).toBeNull();
    expect(
      createHitlApprovalResponses(request, {
        "call-1": "approve",
        "call-2": "reject",
      }),
    ).toHaveLength(2);
  });
});

describe("HITL approval resume options", () => {
  it("uses the current head, resumable values stream, normal recursion limit, and paused send context", () => {
    const responses = createHitlApprovalResponses(request, {
      "call-1": "approve",
      "call-2": "approve",
    })!;
    const options = buildHitlApprovalSubmitOptions({
      threadId: "thread-1",
      settings: DEFAULT_LOCAL_SETTINGS.context,
      responses,
      extraContext: {
        model_name: "model-for-paused-turn",
        model_selection_requested: "model-for-paused-turn",
      },
      conversationReferences: ["referenced-thread"],
    });

    expect(options).toMatchObject({
      threadId: "thread-1",
      checkpoint: null,
      command: { resume: { responses } },
      streamMode: ["values"],
      streamResumable: true,
      config: { recursion_limit: THREAD_RUN_RECURSION_LIMIT },
      context: {
        thread_id: "thread-1",
        model_name: "model-for-paused-turn",
        conversation_references: ["referenced-thread"],
      },
    });
    expect("streamSubgraphs" in options).toBe(false);
  });
});
