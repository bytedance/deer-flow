import { describe, expect, it, beforeEach, vi } from "vitest";

import { detectLocale } from "../index";
import { detectLocaleClient } from "../detect";
import { getLocaleFromCookie, setLocaleInCookie } from "../cookies";

// ---------------------------------------------------------------------------
// detectLocale (index.ts)
// ---------------------------------------------------------------------------
describe("detectLocale", () => {
  it("returns en-US for English browser", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-US");
    expect(detectLocale()).toBe("en-US");
  });

  it("returns zh-CN for Chinese browser", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("zh-CN");
    expect(detectLocale()).toBe("zh-CN");
  });

  it("returns zh-CN for zh-TW browser", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("zh-TW");
    expect(detectLocale()).toBe("zh-CN");
  });

  it("returns en-US for other languages", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("fr-FR");
    expect(detectLocale()).toBe("en-US");
  });
});

// ---------------------------------------------------------------------------
// detectLocaleClient (detect.ts)
// ---------------------------------------------------------------------------
describe("detectLocaleClient", () => {
  beforeEach(() => {
    localStorage.clear();
    // Clear cookies
    document.cookie.split(";").forEach((c) => {
      document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
    });
  });

  it("returns locale from localStorage first", () => {
    localStorage.setItem("locale", "zh-CN");
    expect(detectLocaleClient()).toBe("zh-CN");
  });

  it("ignores invalid localStorage value", () => {
    localStorage.setItem("locale", "invalid");
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-US");
    expect(detectLocaleClient()).toBe("en-US");
  });

  it("falls back to cookie", () => {
    document.cookie = "locale=zh-CN; path=/";
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-US");
    expect(detectLocaleClient()).toBe("zh-CN");
  });

  it("falls back to browser language for Chinese", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("zh-TW");
    expect(detectLocaleClient()).toBe("zh-CN");
  });

  it("defaults to en-US", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    expect(detectLocaleClient()).toBe("en-US");
  });
});

// ---------------------------------------------------------------------------
// Cookie utilities (cookies.ts)
// ---------------------------------------------------------------------------
describe("getLocaleFromCookie", () => {
  beforeEach(() => {
    document.cookie.split(";").forEach((c) => {
      document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
    });
  });

  it("returns null when no cookie set", () => {
    expect(getLocaleFromCookie()).toBeNull();
  });

  it("returns locale value from cookie", () => {
    document.cookie = "locale=en-US; path=/";
    expect(getLocaleFromCookie()).toBe("en-US");
  });

  it("handles multiple cookies", () => {
    document.cookie = "other=value; path=/";
    document.cookie = "locale=zh-CN; path=/";
    expect(getLocaleFromCookie()).toBe("zh-CN");
  });
});

describe("setLocaleInCookie", () => {
  beforeEach(() => {
    document.cookie.split(";").forEach((c) => {
      document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
    });
  });

  it("sets locale cookie", () => {
    setLocaleInCookie("zh-CN");
    expect(getLocaleFromCookie()).toBe("zh-CN");
  });

  it("overwrites existing locale cookie", () => {
    setLocaleInCookie("en-US");
    setLocaleInCookie("zh-CN");
    expect(getLocaleFromCookie()).toBe("zh-CN");
  });
});
