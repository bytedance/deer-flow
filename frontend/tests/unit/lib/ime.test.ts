import { describe, expect, it } from "@rstest/core";
import type { KeyboardEvent } from "react";

import {
  COMPOSITION_CONFIRM_ENTER_MS,
  isCompositionConfirmEnter,
} from "@/lib/ime";

function enter(
  overrides: Partial<KeyboardEvent<HTMLElement>> = {},
): KeyboardEvent<HTMLElement> {
  return {
    key: "Enter",
    shiftKey: false,
    keyCode: 13,
    nativeEvent: { isComposing: false },
    ...overrides,
  } as KeyboardEvent<HTMLElement>;
}

describe("isCompositionConfirmEnter", () => {
  const endedAt = 1_000;

  it("matches the Enter that arrives just after compositionend", () => {
    expect(isCompositionConfirmEnter(enter(), endedAt, endedAt)).toBe(true);
    expect(
      isCompositionConfirmEnter(
        enter(),
        endedAt,
        endedAt + COMPOSITION_CONFIRM_ENTER_MS - 1,
      ),
    ).toBe(true);
  });

  it("lets a later Enter through", () => {
    expect(
      isCompositionConfirmEnter(
        enter(),
        endedAt,
        endedAt + COMPOSITION_CONFIRM_ENTER_MS,
      ),
    ).toBe(false);
    expect(isCompositionConfirmEnter(enter(), 0, endedAt)).toBe(false);
  });

  it("does not claim Shift+Enter or a keydown that is still composing", () => {
    expect(
      isCompositionConfirmEnter(enter({ shiftKey: true }), endedAt, endedAt),
    ).toBe(false);
    expect(
      isCompositionConfirmEnter(enter({ keyCode: 229 }), endedAt, endedAt),
    ).toBe(false);
    expect(
      isCompositionConfirmEnter(
        enter({
          nativeEvent: { isComposing: true } as KeyboardEvent["nativeEvent"],
        }),
        endedAt,
        endedAt,
      ),
    ).toBe(false);
  });
});
