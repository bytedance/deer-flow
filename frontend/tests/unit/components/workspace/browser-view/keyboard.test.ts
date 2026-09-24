import { describe, expect, it } from "@rstest/core";

import { decideBrowserKeyInput } from "@/components/workspace/browser-view/keyboard";

function ctx(
  overrides: Partial<Parameters<typeof decideBrowserKeyInput>[0]> = {},
) {
  return {
    live: true,
    editableTarget: false,
    composing: false,
    key: "a",
    metaKey: false,
    ctrlKey: false,
    ...overrides,
  };
}

describe("decideBrowserKeyInput", () => {
  it("forwards printable chars as text", () => {
    expect(decideBrowserKeyInput(ctx({ key: "a" }))).toEqual({
      type: "text",
      text: "a",
    });
  });

  it("forwards named keys as key presses", () => {
    expect(decideBrowserKeyInput(ctx({ key: "Enter" }))).toEqual({
      type: "key",
      key: "Enter",
    });
    expect(decideBrowserKeyInput(ctx({ key: "ArrowLeft" }))).toEqual({
      type: "key",
      key: "ArrowLeft",
    });
  });

  it("forwards modifier combos as a normalized key chord", () => {
    expect(decideBrowserKeyInput(ctx({ key: "c", metaKey: true }))).toEqual({
      type: "key",
      key: "Meta+C",
    });
    expect(decideBrowserKeyInput(ctx({ key: "a", ctrlKey: true }))).toEqual({
      type: "key",
      key: "Control+A",
    });
  });

  it("does not forward while an IME composition is active", () => {
    // A CJK candidate confirmed with Enter must not submit the remote page.
    expect(
      decideBrowserKeyInput(ctx({ key: "Enter", composing: true })),
    ).toBeNull();
    expect(
      decideBrowserKeyInput(ctx({ key: "a", composing: true })),
    ).toBeNull();
  });

  it("ignores keys when not live or focus is on an editable target", () => {
    expect(
      decideBrowserKeyInput(ctx({ key: "Enter", live: false })),
    ).toBeNull();
    expect(
      decideBrowserKeyInput(ctx({ key: "Enter", editableTarget: true })),
    ).toBeNull();
  });

  it("ignores unmapped named keys", () => {
    expect(decideBrowserKeyInput(ctx({ key: "F5" }))).toBeNull();
  });
});
