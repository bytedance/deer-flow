import { describe, expect, it } from "@rstest/core";

import { loadTranslations } from "@/core/i18n/translations";

describe("core copy loading", () => {
  it("loads only the requested overseas and domestic copy", async () => {
    const [english, chinese] = await Promise.all([
      loadTranslations("en-US"),
      loadTranslations("zh-CN"),
    ]);
    expect(english.inputBox.disclaimer).toBe(
      "DeerFlow is AI and can make mistakes",
    );
    expect(chinese.inputBox.disclaimer).toBe(
      "内容由AI生成，重要信息请务必核查",
    );
    expect(english.channels.descriptions.buzz).toBe(
      "Buzz channels and direct messages through your DeerFlow agent.",
    );
    expect(chinese.channels.descriptions.buzz).toBe(
      "通过 DeerFlow 智能体接收 Buzz 频道消息和私聊。",
    );
  });

  it("loads the Traditional Chinese copy with Taiwan terminology", async () => {
    const taiwanese = await loadTranslations("zh-TW");
    expect(taiwanese.locale.localName).toBe("繁體中文");
    expect(taiwanese.common.settings).toBe("設定");
    expect(taiwanese.common.loadMore).toBe("載入更多");
    expect(taiwanese.inputBox.disclaimer).toBe(
      "內容由AI產生，重要資訊請務必核查",
    );
    expect(taiwanese.channels.descriptions.buzz).toBe(
      "透過 DeerFlow 智慧體接收 Buzz 頻道訊息和私聊。",
    );
  });
});
