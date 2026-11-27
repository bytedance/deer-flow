import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { DocsHtmlLang } from "@/components/docs/docs-html-lang";

type PagefindWindow = Window & {
  pagefind?: { destroy?: () => Promise<void> };
};

beforeEach(() => {
  document.documentElement.lang = "en-US";
  document.documentElement.removeAttribute("data-pagefind-lang");
  Reflect.deleteProperty(window, "pagefind");
});

afterEach(() => {
  cleanup();
  document.documentElement.lang = "en-US";
  document.documentElement.removeAttribute("data-pagefind-lang");
  Reflect.deleteProperty(window, "pagefind");
  rs.restoreAllMocks();
});

describe("DocsHtmlLang", () => {
  it("resets Pagefind when transitioning from en docs to zh docs even if <html lang> is already zh-CN", () => {
    const destroyEn = rs.fn().mockResolvedValue(undefined);
    const { unmount } = render(<DocsHtmlLang lang="en" />);

    expect(document.documentElement.lang).toBe("en-US");
    expect(document.documentElement.getAttribute("data-pagefind-lang")).toBe(
      "en-US",
    );

    // Simulate Nextra initializing English Pagefind on /en/docs.
    (window as PagefindWindow).pagefind = { destroy: destroyEn };

    // Leaving /en/docs to `/` destroys the English Pagefind instance.
    unmount();
    expect(destroyEn).toHaveBeenCalledTimes(1);
    expect((window as PagefindWindow).pagefind).toBeUndefined();

    // Simulate LandingLocaleProvider switching `<html lang>` to zh-CN on `/`
    // and an untracked/stale Pagefind instance still present when entering /zh/docs.
    const destroyStale = rs.fn().mockResolvedValue(undefined);
    document.documentElement.lang = "zh-CN";
    (window as PagefindWindow).pagefind = { destroy: destroyStale };

    render(<DocsHtmlLang lang="zh" />);

    expect(destroyStale).toHaveBeenCalledTimes(1);
    expect((window as PagefindWindow).pagefind).toBeUndefined();
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.documentElement.getAttribute("data-pagefind-lang")).toBe(
      "zh-CN",
    );
  });

  it("resets Pagefind when data-pagefind-lang disagrees with the target docs locale even if <html lang> matches", () => {
    const destroyStale = rs.fn().mockResolvedValue(undefined);
    document.documentElement.lang = "zh-CN";
    document.documentElement.setAttribute("data-pagefind-lang", "en-US");
    (window as PagefindWindow).pagefind = { destroy: destroyStale };

    render(<DocsHtmlLang lang="zh" />);

    expect(destroyStale).toHaveBeenCalledTimes(1);
    expect((window as PagefindWindow).pagefind).toBeUndefined();
    expect(document.documentElement.getAttribute("data-pagefind-lang")).toBe(
      "zh-CN",
    );
  });

  it("preserves Pagefind across re-renders of the same docs language", () => {
    const destroy = rs.fn().mockResolvedValue(undefined);
    const { rerender } = render(<DocsHtmlLang lang="zh" />);
    const instance = { destroy };
    (window as PagefindWindow).pagefind = instance;

    rerender(<DocsHtmlLang lang="zh" />);

    expect(destroy).not.toHaveBeenCalled();
    expect((window as PagefindWindow).pagefind).toBe(instance);
  });
});
