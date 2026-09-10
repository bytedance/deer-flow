import { describe, expect, it } from "@rstest/core";

import {
  formatToolDetail,
  TOOL_PREVIEW_LIMIT,
} from "@/core/messages/tool-detail-preview";

describe("formatToolDetail", () => {
  it("keeps short numeric lists complete beyond the old node budget", () => {
    for (const length of [200, 1000]) {
      const values = Array.from({ length }, (_, i) => i);
      const preview = formatToolDetail(values);
      expect(preview.truncated).toBe(false);
      expect(JSON.parse(preview.text)).toEqual(values);
    }
  });
  it("visibly marks truncated lists and objects", () => {
    for (const value of [Array(20000).fill(0), { text: "x".repeat(20000) }]) {
      const preview = formatToolDetail(value);
      expect(preview.truncated).toBe(true);
      expect(preview.text).toContain("…");
      expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    }
  });
  it.each([42, { secret: "keep-me" }])(
    "preserves a real ellipsis key with value %j when object traversal is truncated",
    (original) => {
      const value: Record<string, unknown> = { "…": original };
      for (let i = 0; i < 20000; i++) value[`k${i}`] = 0;

      const preview = formatToolDetail(value);

      expect(preview.truncated).toBe(true);
      expect(
        preview.text.startsWith(
          JSON.stringify({ "…": original }, null, 2).slice(0, -2),
        ),
      ).toBe(true);
      expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    },
  );
  it("does not shorten a key into an existing ellipsis-suffixed key", () => {
    const original = { secret: "keep-me" };
    const value = {
      "k…": original,
      // Leave two characters for the next key, which used to become "k…".
      padding: "x".repeat(
        TOOL_PREVIEW_LIMIT - "k…secretkeep-mepadding".length - 2,
      ),
      keyThatMustNotBeRenamed: 0,
    };

    const preview = formatToolDetail(value);

    expect(preview.truncated).toBe(true);
    expect(
      preview.text.startsWith(
        JSON.stringify({ "k…": original }, null, 2).slice(0, -2),
      ),
    ).toBe(true);
    expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
  });
  it("omits an oversized key instead of displaying a renamed property", () => {
    const preview = formatToolDetail({
      ["k".repeat(TOOL_PREVIEW_LIMIT + 1)]: 42,
    });

    expect(preview.truncated).toBe(true);
    expect(JSON.parse(preview.text)).toEqual({ "…": "…" });
  });
  it("formats JSON and preserves falsy results and plain text", () => {
    for (const text of ["null", "false", "0", "", "plain text"]) {
      expect(formatToolDetail(text)).toEqual({ text, truncated: false });
    }
    expect(formatToolDetail('{"run_id":42}').text).toBe('{\n  "run_id": 42\n}');
  });
  it("bounds long strings before parsing or serializing", () => {
    const result = formatToolDetail({ content: "x".repeat(1_000_000) });
    expect(result.truncated).toBe(true);
    expect(result.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    expect(formatToolDetail("x".repeat(1_000_000)).text.length).toBe(
      TOOL_PREVIEW_LIMIT,
    );
  });
  it("bounds wide and deep values without reading later getters", () => {
    const wide = Array.from({ length: 1000 }, (_, i) => i);
    Object.defineProperty(wide, "900", {
      get() {
        throw new Error("must not read");
      },
    });
    expect(formatToolDetail(wide).truncated).toBe(true);
    let deep: unknown = "leaf";
    for (let i = 0; i < 1000; i++) deep = { child: deep };
    expect(formatToolDetail(deep).truncated).toBe(true);
  });
  it("does not invoke getters or toJSON and handles cycles", () => {
    const value = {
      get secret() {
        throw new Error("must not read");
      },
      toJSON() {
        throw new Error("must not invoke");
      },
    };
    expect(formatToolDetail(value).truncated).toBe(true);
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    expect(formatToolDetail(cycle).truncated).toBe(true);
  });
  it("renders markup as plain source and limits escaped output", () => {
    expect(formatToolDetail("<script>alert(1)</script>").text).toBe(
      "<script>alert(1)</script>",
    );
    expect(
      formatToolDetail({ text: "\n".repeat(12000) }).text.length,
    ).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
  });
});
