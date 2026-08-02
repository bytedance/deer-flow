import { describe, expect, it } from "@rstest/core";

import { loadTranslations } from "@/core/i18n/translations";

describe("AI disclaimer translations", () => {
  it("loads only the requested overseas and domestic copy", async () => {
    const [english, chinese] = await Promise.all([
      loadTranslations("en-US"),
      loadTranslations("zh-CN"),
    ]);
    expect(english.inputBox.disclaimer).toBe(
      "Deerflow is AI and can make mistakes",
    );
    expect(chinese.inputBox.disclaimer).toBe(
      "内容由AI生成，重要信息请务必核查",
    );
  });
});
