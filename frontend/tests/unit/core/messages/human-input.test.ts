import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import {
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
