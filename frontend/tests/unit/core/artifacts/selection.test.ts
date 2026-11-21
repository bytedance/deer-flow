import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  applyArtifactSelectionDraft,
  artifactReplacement,
  artifactSelectionContext,
  isArtifactRewriteClarification,
  locateArtifactSelection,
  replaceArtifactSelection,
  selectionLines,
  sourceSelectionOffsets,
} from "@/core/artifacts/selection";
import { isSameSidecarContext } from "@/core/sidecar";

describe("artifact selections", () => {
  it.each([
    [1, 2, "\r\n"],
    [0, 1, "a"],
    [2, 5, "b\r\nc"],
    [1, 6, "\r\nb\r\nc\r"],
    [6, 7, "d"],
  ])(
    "maps editor offsets %i–%i to the original line endings",
    (from, to, expected) => {
      const source = "a\r\nb\r\nc\rd";
      const offsets = sourceSelectionOffsets(source, { from, to });
      expect(source.slice(offsets.from, offsets.to)).toBe(expected);
    },
  );

  it("keeps the rewrite marker only on its own clarification chain", () => {
    const messages: Message[] = [
      {
        type: "human",
        content: "Rewrite this",
        additional_kwargs: {
          sidecar_visible_message: true,
          artifact_selection_edit: "edit",
        },
      },
      {
        type: "tool",
        content: "",
        tool_call_id: "tool",
        artifact: {
          human_input: {
            version: 1,
            kind: "human_input_request",
            source: "ask_clarification",
            request_id: "request",
            question: "Which tone?",
            input_mode: "free_text",
          },
        },
      },
    ];
    expect(isArtifactRewriteClarification(messages, "edit", "request")).toBe(
      true,
    );
    expect(isArtifactRewriteClarification(messages, "edit", "other")).toBe(
      false,
    );
    expect(isArtifactRewriteClarification(messages, "other", "request")).toBe(
      false,
    );
    messages.push({
      type: "human",
      content: "Ordinary question",
      additional_kwargs: { sidecar_visible_message: true },
    });
    expect(isArtifactRewriteClarification(messages, "edit", "request")).toBe(
      false,
    );
  });
  it("locates repeated text only inside its selected source block", () => {
    const source = "same\n\nother\n\nsame";
    expect(
      locateArtifactSelection(source, "same", 0, source.length),
    ).toBeNull();
    expect(locateArtifactSelection(source, "same", 13, 17)).toEqual({
      from: 13,
      to: 17,
    });
  });
  it("does not guess source offsets for transformed Markdown", () => {
    expect(
      locateArtifactSelection("hello **world**", "hello world", 0, 15),
    ).toBeNull();
  });
  it("preserves every byte outside the selected span, including CRLF and Unicode", () => {
    const source = "前文\r\n😀selected\r\n尾文";
    const from = source.indexOf("selected"),
      to = from + 8;
    expect(replaceArtifactSelection(source, { source, from, to }, "改写")).toBe(
      "前文\r\n😀改写\r\n尾文",
    );
    expect(selectionLines(source, from, to)).toEqual({
      startLine: 2,
      endLine: 2,
    });
    expect(selectionLines("a\nb\n", 0, 2)).toEqual({
      startLine: 1,
      endLine: 1,
    });
  });
  it("rejects stale drafts and invalid ranges before applying a replacement", () => {
    expect(() =>
      replaceArtifactSelection("new", { source: "old", from: 0, to: 1 }, "x"),
    ).toThrow();
    for (const [from, to] of [
      [-1, 1],
      [2, 1],
      [0, 4],
      [1, 1],
    ]) {
      expect(() =>
        replaceArtifactSelection(
          "old",
          { source: "old", from: from!, to: to! },
          "x",
        ),
      ).toThrow();
    }
  });

  it("keeps identical quotations from different files and line ranges distinct", () => {
    const first = artifactSelectionContext("/a.md", "same\n\nsame", "same", {
      from: 0,
      to: 4,
    });
    const second = artifactSelectionContext("/a.md", "same\n\nsame", "same", {
      from: 6,
      to: 10,
    });
    const other = artifactSelectionContext("/b.md", "same", "same", {
      from: 0,
      to: 4,
    });
    expect(first.label).toBe("/a.md:L1-L1");
    expect(second.label).toBe("/a.md:L3-L3");
    expect(isSameSidecarContext(first, second)).toBe(false);
    expect(isSameSidecarContext(first, other)).toBe(false);
    expect(isSameSidecarContext(first, { ...first })).toBe(true);
  });

  it("rejects changed drafts, conflicting versions and files removed while the agent was answering", () => {
    const draft = {
      filepath: "/a.md",
      baselineContent: "before selected after",
      draftContent: "before selected after",
      baselineSha256: "a",
      conflict: false,
    };
    const edit = {
      id: "edit",
      context: artifactSelectionContext(
        draft.filepath,
        draft.draftContent,
        "selected",
        { from: 7, to: 15 },
      ),
      filepath: draft.filepath,
      threadId: "thread",
      source: draft.draftContent,
      revision: "a",
      from: 7,
      to: 15,
    };
    expect(applyArtifactSelectionDraft(draft, edit, "new")?.draftContent).toBe(
      "before new after",
    );
    for (const changed of [
      undefined,
      { ...draft, conflict: true },
      { ...draft, baselineSha256: "b" },
      { ...draft, draftContent: "manual edit" },
      { ...draft, filepath: "/b.md" },
    ]) {
      expect(applyArtifactSelectionDraft(changed, edit, "new")).toBeNull();
    }
  });

  it("offers only the answer to the current edit's submitted request", () => {
    const request = {
      type: "human" as const,
      content: "rewrite",
      additional_kwargs: {
        sidecar_visible_message: true,
        artifact_selection_edit: "edit",
      },
    };
    const answer = {
      type: "ai" as const,
      content: "```markdown\nreplacement\n```",
    };
    expect(artifactReplacement([answer], "edit")).toBeNull();
    expect(artifactReplacement([request, answer], "other")).toBeNull();
    expect(artifactReplacement([request, answer], "edit")).toBe("replacement");
    expect(
      artifactReplacement(
        [request, { ...answer, content: "    indented code\n" }],
        "edit",
      ),
    ).toBe("    indented code\n");
    expect(
      artifactReplacement(
        [
          request,
          answer,
          { ...request, additional_kwargs: { sidecar_visible_message: true } },
        ],
        "edit",
      ),
    ).toBeNull();
    expect(
      artifactReplacement(
        [request, { ...answer, additional_kwargs: { hide_from_ui: true } }],
        "edit",
      ),
    ).toBeNull();
  });
});
