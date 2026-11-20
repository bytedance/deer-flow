import { describe, expect, it } from "@rstest/core";

import { referenceToken } from "@/components/workspace/mentions/inline-references";
import { getMentionQuery } from "@/components/workspace/mentions/query";

describe("composer mention query", () => {
  for (const kind of ["skill", "file", "conversation"] as const) {
    it(`does not reopen search inside or after a completed ${kind} reference`, () => {
      const token = referenceToken(kind, "id", "报告 [Q4]");
      const text = `Use ${token} later`;
      for (let caret = 5; caret <= 4 + token.length; caret++) {
        expect(getMentionQuery(text, caret)).toBeNull();
      }
    });
  }
  it("still detects a new query next to a reference and incomplete literal text", () => {
    const token = referenceToken("skill", "research", "research");
    for (const text of [`${token} @wri`, `@wri ${token}`]) {
      const start = text.indexOf("@wri");
      expect(getMentionQuery(text, start + 4)).toEqual({
        start,
        end: start + 4,
        query: "wri",
      });
    }
    expect(getMentionQuery("@[notes", 7)?.query).toBe("[notes");
    const malformed = "@[broken](ref:skill:%ZZ)";
    expect(getMentionQuery(malformed, malformed.length)?.query).toBe(
      "[broken](ref:skill:%ZZ)",
    );
  });
  it("replaces only the query at the caret, keeping both sides of the draft", () => {
    const text = "请使用 @research 分析结果";
    const caret = text.indexOf(" 分析");
    const query = getMentionQuery(text, caret)!;
    expect(query.query).toBe("research");
  });
  it("allows Unicode and filenames", () => {
    expect(getMentionQuery("@报告.pdf", 7)?.query).toBe("报告.pdf");
    expect(getMentionQuery("（@报告", 4)?.query).toBe("报告");
  });
  it("does not activate in an email, URL, or completed text", () => {
    for (const text of [
      "a@example.com",
      "https://host/@name",
      "@name ",
      "@@name",
      "path/@name",
    ]) {
      expect(getMentionQuery(text, text.length)).toBeNull();
    }
  });
  it("keeps an unselected query as literal text", () => {
    const text = "@unknown";
    expect(getMentionQuery(text, text.length)).toEqual({
      start: 0,
      end: 8,
      query: "unknown",
    });
    expect(text).toBe("@unknown");
  });
});
