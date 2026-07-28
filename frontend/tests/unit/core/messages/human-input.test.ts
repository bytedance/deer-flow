import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import {
  buildHumanInputFormSubmissionValue,
  buildHumanInputFormSummary,
  buildHumanInputResponseText,
  buildInitialHumanInputFormValues,
  createHumanInputOptionResponse,
  createHumanInputTextResponse,
  deriveHumanInputThreadState,
  extractHumanInputRequest,
  extractHumanInputResponse,
  hasOpenHumanInputRequest,
  readHumanInputFormValue,
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

test("form submission value is collision-free via the JSON block", () => {
  const request = extractHumanInputRequest(
    toolMessage({
      ...formPayload,
      fields: [
        { name: "a", label: "A", type: "text", required: false },
        { name: "b", label: "B", type: "text", required: false },
      ],
    }),
  )!;

  const first = buildHumanInputFormSubmissionValue(request, {
    a: "x; B: y",
    b: "z",
  });
  const second = buildHumanInputFormSubmissionValue(request, {
    a: "x",
    b: "y; B: z",
  });

  expect(first).not.toBe(second);
  expect(first).toContain('[values: {"a":"x; B: y","b":"z"}]');
  expect(second).toContain('[values: {"a":"x","b":"y; B: z"}]');
  // Readable prefix is retained for display.
  expect(first.startsWith("A: x; B: y; B: z")).toBe(true);
});

test("rejects select options with empty values or duplicates", () => {
  const withOptions = (
    options: Array<{ id: string; label: string; value: string }>,
  ) =>
    extractHumanInputRequest(
      toolMessage({
        ...formPayload,
        fields: [
          {
            name: "category",
            label: "Category",
            type: "select",
            required: true,
            options,
          },
        ],
      }),
    );

  // Empty option value would crash Radix <SelectItem value="">.
  expect(withOptions([{ id: "o1", label: "travel", value: "" }])).toBeNull();
  // Duplicate option ids / values.
  expect(
    withOptions([
      { id: "o1", label: "travel", value: "travel" },
      { id: "o1", label: "meals", value: "meals" },
    ]),
  ).toBeNull();
  expect(
    withOptions([
      { id: "o1", label: "travel", value: "travel" },
      { id: "o2", label: "travel-again", value: "travel" },
    ]),
  ).toBeNull();
});

test("rejects duplicate field names and enforces the form/version binding", () => {
  expect(
    extractHumanInputRequest(
      toolMessage({
        ...formPayload,
        fields: [
          { name: "amount", label: "Amount", type: "number", required: true },
          { name: "amount", label: "Again", type: "text", required: false },
        ],
      }),
    ),
  ).toBeNull();
  // form mode is a v2 construct; a v1 payload carrying it is malformed.
  expect(
    extractHumanInputRequest(toolMessage({ ...formPayload, version: 1 })),
  ).toBeNull();
  // and v2 without form has no defined meaning yet.
  expect(
    extractHumanInputRequest(
      toolMessage({
        ...requestPayload,
        version: 2,
      }),
    ),
  ).toBeNull();
});

test("rejects form fields with reserved prototype names", () => {
  for (const reserved of ["__proto__", "constructor", "toString"]) {
    expect(
      extractHumanInputRequest(
        toolMessage({
          ...formPayload,
          fields: [
            { name: reserved, label: "Amount", type: "number", required: true },
          ],
        }),
      ),
    ).toBeNull();
  }
});

test("readHumanInputFormValue ignores inherited prototype properties", () => {
  const values: Record<string, string> = { amount: "300" };

  expect(readHumanInputFormValue(values, "amount")).toBe("300");
  expect(readHumanInputFormValue(values, "toString")).toBeUndefined();
  expect(readHumanInputFormValue(values, "constructor")).toBeUndefined();
  expect(readHumanInputFormValue(values, "__proto__")).toBeUndefined();
});

test("buildInitialHumanInputFormValues seeds checkbox fields to false", () => {
  const request = extractHumanInputRequest(
    toolMessage({
      ...formPayload,
      fields: [
        { name: "amount", label: "Amount", type: "number", required: true },
        { name: "urgent", label: "Urgent", type: "checkbox", required: false },
      ],
    }),
  )!;

  expect(buildInitialHumanInputFormValues(request.fields ?? [])).toEqual({
    urgent: false,
  });
});

test("summary renders an untouched checkbox as an explicit no", () => {
  const request = extractHumanInputRequest(
    toolMessage({
      ...formPayload,
      fields: [
        { name: "amount", label: "Amount", type: "number", required: true },
        { name: "urgent", label: "Urgent", type: "checkbox", required: false },
      ],
    }),
  )!;
  const values = {
    amount: "300",
    ...buildInitialHumanInputFormValues(request.fields ?? []),
  };

  expect(buildHumanInputFormSummary(request, values)).toBe(
    "Amount: 300; Urgent: no",
  );
});

test("a plain reply closes only the latest unanswered request", () => {
  const olderPayload = {
    ...formPayload,
    request_id: "clarification:call-older",
  };
  const state = deriveHumanInputThreadState([
    toolMessage(olderPayload),
    toolMessage(formPayload),
    {
      type: "human",
      content: "answer to the second question",
    } as unknown as Message,
  ]);

  // The reply answers the request the user was looking at (the latest); the
  // older decision must not be silently swallowed with the same text.
  expect(state.answeredResponses.get("clarification:call-form")?.value).toBe(
    "answer to the second question",
  );
  expect(state.answeredResponses.has("clarification:call-older")).toBe(false);
  expect(state.latestOpenRequestId).toBe("clarification:call-older");
});

test("a visible plain human reply bypasses and closes an open request", () => {
  // The normal composer deliberately sends no structured response metadata.
  // Treating its message as the answer lets users bypass the form and also
  // preserves compatibility with old frontends that render v2 as plain text.
  const messages = [
    toolMessage(formPayload),
    {
      type: "human",
      content: "金额 300，类别差旅",
    } as unknown as Message,
  ];
  const state = deriveHumanInputThreadState(messages);

  expect(state.latestOpenRequestId).toBeNull();
  const answered = state.answeredResponses.get("clarification:call-form");
  expect(answered?.response_kind).toBe("text");
  expect(answered?.value).toBe("金额 300，类别差旅");
  expect(hasOpenHumanInputRequest([toolMessage(formPayload)])).toBe(true);
  expect(hasOpenHumanInputRequest(messages)).toBe(false);
});

test("a visible human message before the request does not close it", () => {
  const state = deriveHumanInputThreadState([
    {
      type: "human",
      content: "帮我提交报销",
    } as unknown as Message,
    toolMessage(formPayload),
  ]);

  expect(state.latestOpenRequestId).toBe("clarification:call-form");
});

test("hidden non-response messages do not close an open request", () => {
  const state = deriveHumanInputThreadState([
    toolMessage(formPayload),
    {
      type: "human",
      content: "internal context",
      additional_kwargs: { hide_from_ui: true },
    } as unknown as Message,
  ]);

  expect(state.latestOpenRequestId).toBe("clarification:call-form");
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
