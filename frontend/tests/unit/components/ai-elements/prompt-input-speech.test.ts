import { describe, expect, test } from "vitest";

import { appendTranscriptionToInput } from "@/components/ai-elements/prompt-input";

describe("appendTranscriptionToInput", () => {
  test("returns the transcript when the current input is empty", () => {
    expect(appendTranscriptionToInput("", "Hello world")).toBe("Hello world");
  });

  test("appends the transcript to the existing input with a single separator", () => {
    expect(appendTranscriptionToInput("Draft question", "next sentence")).toBe(
      "Draft question next sentence",
    );
  });

  test("ignores empty transcript fragments", () => {
    expect(appendTranscriptionToInput("Draft question", "   ")).toBe(
      "Draft question",
    );
  });
});
