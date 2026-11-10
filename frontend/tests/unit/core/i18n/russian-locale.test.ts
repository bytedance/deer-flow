import { describe, expect, it } from "@rstest/core";
import {
  DEFAULT_LOCALE,
  SUPPORTED_LOCALES,
  getLocaleByLang,
  normalizeLocale,
} from "@/core/i18n/locale";
import { getSpeechRecognitionLanguage } from "@/core/voice-input/speech-recognition";
import { parsePreferences } from "@/core/settings/preferences-sync";

describe("Russian locale", () => {
  it("registers ru-RU without changing the default", () => {
    expect(SUPPORTED_LOCALES).toContain("ru-RU");
    expect(DEFAULT_LOCALE).toBe("en-US");
  });

  it("normalizes Russian browser and stored language variants", () => {
    expect(getLocaleByLang("ru")).toBe("ru-RU");
    expect(normalizeLocale("ru")).toBe("ru-RU");
    expect(normalizeLocale("ru-RU")).toBe("ru-RU");
    expect(normalizeLocale("RU-ru")).toBe("ru-RU");
    expect(normalizeLocale("ru-BY")).toBe("ru-RU");
  });

  it("retains supported locales and the English fallback", () => {
    expect(normalizeLocale("en-US")).toBe("en-US");
    expect(normalizeLocale("zh-Hant")).toBe("zh-CN");
    expect(normalizeLocale("fr-FR")).toBe("en-US");
    expect(normalizeLocale("<invalid>")).toBe("en-US");
  });

  it("uses Russian for browser speech recognition", () => {
    expect(getSpeechRecognitionLanguage("ru-RU")).toBe("ru-RU");
  });

  it("accepts ru-RU user preferences and rejects unsupported languages", () => {
    expect(parsePreferences({ locale: "ru-RU" }).locale).toBe("ru-RU");
    expect(parsePreferences({ locale: "fr-FR" }).locale).toBeUndefined();
  });
});
