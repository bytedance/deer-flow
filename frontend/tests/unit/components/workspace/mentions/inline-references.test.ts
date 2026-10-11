import { describe, expect, it } from "@rstest/core";

import {
  inlineReferences,
  reconcileConversationReferences,
  referenceToken,
  restoreReferenceLabels,
} from "@/components/workspace/mentions/inline-references";

const text = ["one", "two", "one", "self", "three"]
  .map((id) => referenceToken("conversation", id, `Title ${id}`))
  .join(" ");
describe("conversation reference reconciliation", () => {
  it("uses token order, deduplicates, excludes self, and preserves known display metadata", () => {
    const result = reconcileConversationReferences(
      text,
      [{ threadId: "one", title: "Known", agentName: "writer" }],
      { enabled: true, maxReferences: 2, isLoading: false, isSuccess: true },
      "self",
    );
    expect(result.references).toEqual([
      { threadId: "one", title: "Known", agentName: "writer" },
      { threadId: "two", title: "Title two" },
    ]);
    expect(inlineReferences(result.text).map((ref) => ref.id)).toEqual([
      "one",
      "two",
      "one",
    ]);
    expect(result.text).toContain("@Title self @Title three");
  });
  it("retains pending text, then flattens disabled references without losing user words", () => {
    expect(
      reconcileConversationReferences(
        text,
        [],
        { enabled: false, maxReferences: 0, isLoading: true, isSuccess: false },
        "self",
      ),
    ).toEqual({ text, references: [] });
    const result = reconcileConversationReferences(
      text,
      [],
      { enabled: false, maxReferences: 3, isLoading: false, isSuccess: true },
      "self",
    );
    expect(result.references).toEqual([]);
    expect(result.text).toBe(
      "@Title one @Title two @Title one @Title self @Title three",
    );
  });
});

describe("polished reference labels", () => {
  for (const [kind, shortLabel, longLabel] of [
    ["skill", "research", "research-tools"],
    ["file", "report", "report.pdf"],
    ["conversation", "调研", "调研计划（Q4）"],
    ["file", "notes[1]", "notes[1].txt"],
  ] as const) {
    it(`restores reordered overlapping ${kind} labels: ${longLabel}`, () => {
      const short = referenceToken(kind, "short-id", shortLabel);
      const long = referenceToken(kind, "long-id", longLabel);
      expect(
        restoreReferenceLabels(
          `Use ${short} after ${long}`,
          `Use @${longLabel} first, then @${shortLabel}.`,
        ),
      ).toBe(`Use ${long} first, then ${short}.`);
    });
  }
  it("does not consume a longer unselected word", () => {
    const token = referenceToken("skill", "research", "research");
    expect(
      restoreReferenceLabels(
        token,
        "Keep @research-tools unchanged; use @research.",
      ),
    ).toBe(`Keep @research-tools unchanged; use ${token}.`);
  });
  it("replaces each occurrence once without scanning inserted tokens", () => {
    const token = referenceToken("skill", "id", "research");
    expect(
      restoreReferenceLabels(
        `${token} ${token}`,
        "@research then @research and @research",
      ),
    ).toBe(`${token} then ${token} and @research`);
  });
  it("retains omitted selections in their original order", () => {
    const a = referenceToken("skill", "a", "A");
    const b = referenceToken("file", "b", "B");
    expect(
      restoreReferenceLabels(`${a} then ${b}`, "Task without labels"),
    ).toBe(`${a} ${b} Task without labels`);
  });
});

it("preserves known reference metadata while discovery has failed, including edits", () => {
  const kept = { threadId: "one", title: "Known", agentName: "writer" };
  const result = reconcileConversationReferences(
    referenceToken("conversation", "one", "Title one") + " edited",
    [kept, { threadId: "deleted", title: "Deleted" }],
    { enabled: false, maxReferences: 0, isLoading: false, isSuccess: false },
    "self",
  );
  expect(result.references).toEqual([kept]);
  expect(inlineReferences(result.text).map((ref) => ref.id)).toEqual(["one"]);
});

it("restores labels adjacent to Chinese prose", () => {
  const token = referenceToken("skill", "research", "research");
  expect(
    restoreReferenceLabels(
      `请用${token}，总结资料。`,
      "请用@research，总结资料。",
    ),
  ).toBe(`请用${token}，总结资料。`);
});
