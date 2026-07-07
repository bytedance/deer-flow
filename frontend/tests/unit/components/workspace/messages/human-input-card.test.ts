import { describe, expect, it } from "@rstest/core";
import { createElement, type KeyboardEvent } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  HumanInputCard,
  shouldSubmitHumanInputTextOnKeyDown,
} from "@/components/workspace/messages/human-input-card";
import { I18nContext } from "@/core/i18n/context";
import type {
  HumanInputRequest,
  HumanInputResponse,
} from "@/core/messages/human-input";

const request: HumanInputRequest = {
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

describe("HumanInputCard", () => {
  it("renders request text, options, and the other-answer input", () => {
    const html = renderCard();

    expect(html).toContain("Need your help");
    expect(html).toContain("Need the target environment.");
    expect(html).toContain("Which environment should I deploy to?");
    expect(html).toContain("development");
    expect(html).toContain("staging");
    expect(html).toContain("Other answer");
    expect(html).toContain("Type another answer...");
  });

  it("renders answered state as disabled with the selected value", () => {
    const response: HumanInputResponse = {
      version: 1,
      kind: "human_input_response",
      source: "ask_clarification",
      request_id: "clarification:call-abc",
      response_kind: "option",
      option_id: "option-2",
      value: "staging",
    };
    const html = renderCard({ answeredResponse: response });

    expect(html).toContain("Answered");
    expect(html).toContain("Answered: staging");
    expect(html).toContain("disabled");
  });

  it("renders read-only state when no submit handler is available", () => {
    const html = renderCard({ onSubmit: undefined });

    expect(html).toContain("Read only");
    expect(html).toContain("disabled");
  });

  it("renders markdown in question field (bold, lists)", () => {
    const html = renderCard({
      request: {
        ...request,
        question:
          "你想写什么样的小说？\n\n1. **题材/类型**：科幻、奇幻\n2. **篇幅**：短篇、中篇",
        input_mode: "free_text",
        options: undefined,
      },
    });

    expect(html).toContain("题材/类型");
    expect(html).toContain("篇幅");
    expect(html).not.toContain("**题材/类型**");
    expect(html).not.toContain("**篇幅**");
  });

  it("does not submit text with Enter while IME composition is active", () => {
    expect(shouldSubmitHumanInputTextOnKeyDown(keyEvent())).toBe(true);
    expect(
      shouldSubmitHumanInputTextOnKeyDown(keyEvent({ shiftKey: true })),
    ).toBe(false);
    expect(
      shouldSubmitHumanInputTextOnKeyDown(keyEvent({ isComposing: true })),
    ).toBe(false);
    expect(
      shouldSubmitHumanInputTextOnKeyDown(keyEvent({ keyCode: 229 })),
    ).toBe(false);
    expect(shouldSubmitHumanInputTextOnKeyDown(keyEvent(), true)).toBe(false);
  });
});

function renderCard(props: Partial<Parameters<typeof HumanInputCard>[0]> = {}) {
  return renderToStaticMarkup(
    createElement(
      I18nContext.Provider,
      {
        value: {
          locale: "en-US",
          setLocale: () => undefined,
        },
      },
      createElement(HumanInputCard, {
        request,
        onSubmit: () => undefined,
        ...props,
      }),
    ),
  );
}

function keyEvent({
  isComposing = false,
  key = "Enter",
  keyCode = 13,
  shiftKey = false,
}: {
  isComposing?: boolean;
  key?: string;
  keyCode?: number;
  shiftKey?: boolean;
} = {}) {
  return {
    key,
    keyCode,
    nativeEvent: { isComposing },
    shiftKey,
  } as unknown as KeyboardEvent<HTMLTextAreaElement>;
}
