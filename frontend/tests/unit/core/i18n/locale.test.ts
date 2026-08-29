import { describe, expect, it } from "@rstest/core";

import { normalizeLocale } from "@/core/i18n/locale";

describe("normalizeLocale", () => {
  it("maps Traditional Chinese tags to zh-TW", () => {
    expect(normalizeLocale("zh-TW")).toBe("zh-TW");
    expect(normalizeLocale("zh-Hant")).toBe("zh-TW");
    expect(normalizeLocale("zh-Hant-TW")).toBe("zh-TW");
    expect(normalizeLocale("zh-HK")).toBe("zh-TW");
  });

  it("keeps Simplified Chinese tags on zh-CN", () => {
    expect(normalizeLocale("zh-CN")).toBe("zh-CN");
    expect(normalizeLocale("zh-Hans")).toBe("zh-CN");
    expect(normalizeLocale("zh")).toBe("zh-CN");
  });

  it("falls back to the default locale", () => {
    expect(normalizeLocale("fr-FR")).toBe("en-US");
    expect(normalizeLocale(null)).toBe("en-US");
    expect(normalizeLocale(undefined)).toBe("en-US");
  });
});
