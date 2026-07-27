import { describe, expect, it } from "@rstest/core";

import { translations } from "@/core/i18n/translations";

describe("AI disclaimer translations", () => {
  it("provides the requested overseas and domestic copy", () => {
    expect(translations["en-US"].inputBox.disclaimer).toBe(
      "Deerflow is AI and can make mistakes",
    );
    expect(translations["zh-CN"].inputBox.disclaimer).toBe(
      "内容由AI生成，重要信息请务必核查",
    );
  });
});
