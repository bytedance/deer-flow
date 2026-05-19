/**
 * Tests for the KnowledgeBaseSelector cleanup invariants (Sprint C.2.1/C.2.2).
 *
 * The test surface is the pair of pure helpers exported under
 * `__test_only`: `knowledgeBaseIdSignature` (so the cleanup effect's
 * dep array is a stable primitive) and `cleanSelection` (so the effect
 * is a no-op when nothing actually drifted, preventing the live-loop
 * the previous `hasCleaned` ref was working around).
 */
import { describe, expect, it } from "vitest";

import { __test_only } from "@/components/workspace/knowledge-base-selector";

const { knowledgeBaseIdSignature, cleanSelection } = __test_only;

describe("knowledgeBaseIdSignature", () => {
  it("returns a stable primitive for identical id sets in any order", () => {
    const sigA = knowledgeBaseIdSignature([{ id: "kb-3" }, { id: "kb-1" }, { id: "kb-2" }]);
    const sigB = knowledgeBaseIdSignature([{ id: "kb-1" }, { id: "kb-2" }, { id: "kb-3" }]);
    expect(sigA).toBe(sigB);
  });

  it("changes when an id is added", () => {
    const before = knowledgeBaseIdSignature([{ id: "kb-1" }]);
    const after = knowledgeBaseIdSignature([{ id: "kb-1" }, { id: "kb-2" }]);
    expect(before).not.toBe(after);
  });

  it("changes when an id is removed", () => {
    const before = knowledgeBaseIdSignature([{ id: "kb-1" }, { id: "kb-2" }]);
    const after = knowledgeBaseIdSignature([{ id: "kb-1" }]);
    expect(before).not.toBe(after);
  });

  it("returns empty string for empty input (still a stable primitive)", () => {
    expect(knowledgeBaseIdSignature([])).toBe("");
  });
});

describe("cleanSelection", () => {
  it("returns the same reference when every selected id is still valid", () => {
    const selection = { enabled: true, selected_ids: ["kb-1", "kb-2"] };
    const result = cleanSelection(selection, new Set(["kb-1", "kb-2", "kb-3"]));
    // Reference equality is the contract — the effect uses `next !== selection`
    // to skip onSelectionChange. Returning a fresh object would re-fire the
    // effect via the parent's setState and live-lock.
    expect(result).toBe(selection);
  });

  it("strips ids that are no longer visible", () => {
    const selection = {
      enabled: true,
      selected_ids: ["kb-1", "kb-deleted", "kb-2"],
    };
    const result = cleanSelection(selection, new Set(["kb-1", "kb-2"]));
    expect(result).not.toBe(selection);
    expect(result.selected_ids).toEqual(["kb-1", "kb-2"]);
    expect(result.enabled).toBe(true);
  });

  it("forces enabled=false when all selected ids disappear", () => {
    const selection = {
      enabled: true,
      selected_ids: ["kb-deleted-a", "kb-deleted-b"],
    };
    const result = cleanSelection(selection, new Set(["kb-other"]));
    expect(result.selected_ids).toEqual([]);
    // Why this matters: leaving enabled=true with no IDs would make the
    // next chat turn retrieve from an empty set and silently produce zero
    // results — a confusing state for the user.
    expect(result.enabled).toBe(false);
  });

  it("preserves the original selection order for surviving ids", () => {
    const selection = {
      enabled: true,
      selected_ids: ["kb-3", "kb-1", "kb-2"],
    };
    const result = cleanSelection(selection, new Set(["kb-1", "kb-2", "kb-3"]));
    // Same reference, same order — no churn.
    expect(result).toBe(selection);
    expect(result.selected_ids).toEqual(["kb-3", "kb-1", "kb-2"]);
  });

  it("is idempotent: running cleanSelection on its own output is a no-op", () => {
    const original = {
      enabled: true,
      selected_ids: ["kb-1", "kb-deleted"],
    };
    const validIds = new Set(["kb-1"]);
    const cleaned = cleanSelection(original, validIds);
    const cleanedAgain = cleanSelection(cleaned, validIds);
    expect(cleanedAgain).toBe(cleaned);
  });
});
