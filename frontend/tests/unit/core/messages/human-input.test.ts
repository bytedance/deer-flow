import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import {
  buildHumanInputFormSummary,
  buildHumanInputResponseText,
  createHumanInputOptionResponse,
  createHumanInputTextResponse,
  deriveHumanInputThreadState,
  extractHumanInputRequest,
  extractHumanInputResponse,
  hasOpenHumanInputRequest,
  shouldClearPendingHumanInputOnThreadError,
} from "@/core/messages/human-input";

const requestPayload = {
  version: 1,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:call-abc",
  tool_call_id: "call-abc",
  clarification_type: "approach_choice",
  question: "Which environment should I deploy to?",
  context: "Need the target environment.",
  input_mode: "choice_with_other",
  options: [
    { id: "option-1", label: "development", value: "development" },
    { id: "option-2", label: "staging", value: "staging" },
  ],
};

test("extractHumanInputRequest reads a valid tool artifact payload", () => {
  const message = {
    type: "tool",
    name: "ask_clarification",
    content: "fallback",
    artifact: {
      human_input: requestPayload,
    },
  } as unknown as Message;

  expect(extractHumanInputRequest(message)).toEqual(requestPayload);
});

test("extractHumanInputRequest rejects malformed artifacts", () => {
  const message = {
    type: "tool",
    name: "ask_clarification",
    content: "fallback",
    artifact: {
      human_input: {
        ...requestPayload,
        options: [{ id: "option-1", label: "missing value" }],
      },
    },
  } as unknown as Message;

  expect(extractHumanInputRequest(message)).toBeNull();
});

test("extractHumanInputResponse reads valid human message metadata", () => {
  const response = {
    version: 1,
    kind: "human_input_response",
    source: "ask_clarification",
    request_id: "clarification:call-abc",
    response_kind: "option",
    option_id: "option-2",
    value: "staging",
  };
  const message = {
    type: "human",
    content: "For your clarification, my answer is: staging",
    additional_kwargs: {
      hide_from_ui: true,
      human_input_response: response,
    },
  } as unknown as Message;

  expect(extractHumanInputResponse(message)).toEqual(response);
});

test("derives answered card state from hidden human input responses", () => {
  const response = {
    version: 1,
    kind: "human_input_response",
    source: "ask_clarification",
    request_id: "clarification:call-abc",
    response_kind: "option",
    option_id: "option-2",
    value: "staging",
  };
  const state = deriveHumanInputThreadState([
    {
      type: "tool",
      name: "ask_clarification",
      content: "fallback",
      artifact: {
        human_input: requestPayload,
      },
    } as unknown as Message,
    {
      type: "human",
      content: "For your clarification, my answer is: staging",
      additional_kwargs: {
        hide_from_ui: true,
        human_input_response: response,
      },
    } as unknown as Message,
  ]);

  expect(state.answeredResponses.get("clarification:call-abc")).toEqual(
    response,
  );
  expect(state.latestOpenRequestId).toBeNull();
});

test("detects whether a thread has an open human input request", () => {
  const requestMessage = {
    type: "tool",
    name: "ask_clarification",
    content: "fallback",
    artifact: {
      human_input: requestPayload,
    },
  } as unknown as Message;
  const responseMessage = {
    type: "human",
    content: "For your clarification, my answer is: staging",
    additional_kwargs: {
      hide_from_ui: true,
      human_input_response: {
        version: 1,
        kind: "human_input_response",
        source: "ask_clarification",
        request_id: "clarification:call-abc",
        response_kind: "option",
        option_id: "option-2",
        value: "staging",
      },
    },
  } as unknown as Message;

  expect(hasOpenHumanInputRequest([requestMessage])).toBe(true);
  expect(hasOpenHumanInputRequest([requestMessage, responseMessage])).toBe(
    false,
  );
});

test("detects new thread errors that should unlock pending human input cards", () => {
  const previousError = new Error("old failure");
  const currentError = new Error("stream failed");

  expect(
    shouldClearPendingHumanInputOnThreadError({
      currentError,
      pendingRequestCount: 1,
      previousError: undefined,
    }),
  ).toBe(true);
  expect(
    shouldClearPendingHumanInputOnThreadError({
      currentError,
      pendingRequestCount: 0,
      previousError: undefined,
    }),
  ).toBe(false);
  expect(
    shouldClearPendingHumanInputOnThreadError({
      currentError: previousError,
      pendingRequestCount: 1,
      previousError,
    }),
  ).toBe(false);
  expect(
    shouldClearPendingHumanInputOnThreadError({
      currentError: undefined,
      pendingRequestCount: 1,
      previousError: currentError,
    }),
  ).toBe(false);
});

test("creates option and text responses for a request", () => {
  const request = extractHumanInputRequest({
    type: "tool",
    name: "ask_clarification",
    content: "fallback",
    artifact: {
      human_input: requestPayload,
    },
  } as unknown as Message);

  expect(request).not.toBeNull();
  const optionResponse = createHumanInputOptionResponse(
    request!,
    request!.options![1]!,
  );
  const textResponse = createHumanInputTextResponse(
    request!,
    "Use blue-green deployment",
  );

  expect(optionResponse).toEqual({
    version: 1,
    kind: "human_input_response",
    source: "ask_clarification",
    request_id: "clarification:call-abc",
    response_kind: "option",
    option_id: "option-2",
    value: "staging",
  });
  expect(textResponse).toEqual({
    version: 1,
    kind: "human_input_response",
    source: "ask_clarification",
    request_id: "clarification:call-abc",
    response_kind: "text",
    value: "Use blue-green deployment",
  });
  expect(buildHumanInputResponseText(request!, optionResponse)).toBe(
    'For your clarification "Which environment should I deploy to?", my answer is: staging',
  );
});

const formPayload = {
  version: 2,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:call-form",
  question: "Please provide the expense details.",
  input_mode: "form",
  fields: [
    { name: "amount", label: "Amount", type: "number", required: true },
    {
      name: "category",
      label: "Category",
      type: "select",
      required: true,
      options: [
        { id: "category-option-1", label: "travel", value: "travel" },
        { id: "category-option-2", label: "meals", value: "meals" },
      ],
    },
    {
      name: "receipts",
      label: "Receipts",
      type: "multi_select",
      required: false,
      options: [
        { id: "receipts-option-1", label: "A-1", value: "A-1" },
        { id: "receipts-option-2", label: "A-2", value: "A-2" },
      ],
    },
    { name: "note", label: "note", type: "textarea", required: false },
  ],
};

function toolMessage(payload: unknown): Message {
  return {
    type: "tool",
    name: "ask_clarification",
    content: "fallback",
    artifact: { human_input: payload },
  } as unknown as Message;
}

test("parses a v2 form request", () => {
  expect(extractHumanInputRequest(toolMessage(formPayload))).toEqual(
    formPayload,
  );
});

test("rejects a form request without fields", () => {
  expect(
    extractHumanInputRequest(toolMessage({ ...formPayload, fields: [] })),
  ).toBeNull();
});

test("rejects a form request with malformed fields", () => {
  expect(
    extractHumanInputRequest(
      toolMessage({
        ...formPayload,
        fields: [{ label: "missing name", type: "text" }],
      }),
    ),
  ).toBeNull();
  expect(
    extractHumanInputRequest(
      toolMessage({
        ...formPayload,
        fields: [{ name: "amount", label: "Amount", type: "slider" }],
      }),
    ),
  ).toBeNull();
});

test("rejects unknown protocol versions", () => {
  expect(
    extractHumanInputRequest(toolMessage({ ...formPayload, version: 3 })),
  ).toBeNull();
});

test("builds a readable form summary submitted as a v1 text response", () => {
  const request = extractHumanInputRequest(toolMessage(formPayload))!;
  const values = {
    amount: "300",
    category: "travel",
    receipts: ["A-1", "A-2"],
    note: "",
  };

  const summary = buildHumanInputFormSummary(request, values);
  expect(summary).toBe("Amount: 300; Category: travel; Receipts: A-1, A-2");

  // Request-side-only protocol scope: form answers reuse the existing v1
  // text response — no structured response kind is introduced.
  expect(createHumanInputTextResponse(request, summary)).toEqual({
    version: 1,
    kind: "human_input_response",
    source: "ask_clarification",
    request_id: "clarification:call-form",
    response_kind: "text",
    value: "Amount: 300; Category: travel; Receipts: A-1, A-2",
  });
});

test("derives answered state for a form request answered by text", () => {
  const response = {
    version: 1,
    kind: "human_input_response",
    source: "ask_clarification",
    request_id: "clarification:call-form",
    response_kind: "text",
    value: "Amount: 300",
  };
  const state = deriveHumanInputThreadState([
    toolMessage(formPayload),
    {
      type: "human",
      content: "answer",
      additional_kwargs: { hide_from_ui: true, human_input_response: response },
    } as unknown as Message,
  ]);

  expect(state.answeredResponses.get("clarification:call-form")).toEqual(
    response,
  );
  expect(state.latestOpenRequestId).toBeNull();
});
