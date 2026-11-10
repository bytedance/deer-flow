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
    expect(chinese.knowledge.scope.title).toBe("知识库范围");
  });

  it("loads a Russian dictionary while preserving untranslated functional entries", async () => {
    const [english, russian] = await Promise.all([
      loadTranslations("en-US"),
      loadTranslations("ru-RU"),
    ]);
    expect(russian.locale.localName).toBe("Русский");
    expect(russian.common.save).toBe("Сохранить");
    expect(russian.inputBox.placeholder).toBe("Чем я могу помочь?");
    expect(russian.settings.appearance.languageTitle).toBe("Язык");
    expect(russian.common.showingOf(3, 10)).toBe("Показано 3 из 10");
    expect(russian.inputBox.mentionMultipleSkills).toContain("навыков");
    expect(russian.settings.sections.models).toBe("Модели");
    expect(russian.settings.sections.users).toBe("Пользователи");
    expect(russian.settings.sections.account).toBe("Учётная запись");
    expect(russian.settings.models.title).toBe("Модели");
    expect(russian.settings.users.title).toBe("Управление пользователями");
    expect(russian.tokenUsage.title).toBe("Использование токенов");
    expect(russian.tokenUsage.view).toBe("Отображение");
    expect(russian.tokenUsage.presets.perTurn).toBe("По сообщениям");
    expect(russian.inputBox.suggestions[0]?.suggestion).toBe("Написать");
    expect(russian.inputBox.suggestions[1]?.suggestion).toBe("Исследовать");
    expect(russian.common.loadingSettings).toBe("Загрузка настроек…");
    expect(russian.common.selectFile).toBe("Выберите файл");
    expect(english.common.selectFile).toBeUndefined();
  });
});
