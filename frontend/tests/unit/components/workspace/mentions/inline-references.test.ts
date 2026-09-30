import { describe, expect, it } from "@rstest/core";

import {
  inlineReferences,
  reconcileConversationReferences,
  referenceToken,
} from "@/components/workspace/mentions/inline-references";

const text = ["one", "two", "one", "self", "three"]
  .map((id) => referenceToken("conversation", id, `Title ${id}`))
  .join(" ");
describe("conversation reference reconciliation", () => {
  it("uses token order, deduplicates, excludes self, and preserves known display metadata", () => {
    const result = reconcileConversationReferences(
      text,
      [{ threadId: "one", title: "Known", agentName: "writer" }],
      { enabled: true, maxReferences: 2, isLoading: false },
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
        { enabled: false, maxReferences: 0, isLoading: true },
        "self",
      ),
    ).toEqual({ text, references: [] });
    const result = reconcileConversationReferences(
      text,
      [],
      { enabled: false, maxReferences: 3, isLoading: false },
      "self",
    );
    expect(result.references).toEqual([]);
    expect(result.text).toBe(
      "@Title one @Title two @Title one @Title self @Title three",
    );
  });
});
