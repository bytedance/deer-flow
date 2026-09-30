import { describe, expect, it } from "@rstest/core";

import { getMentionQuery } from "@/components/workspace/mentions/query";

describe("composer mention query", () => {
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
