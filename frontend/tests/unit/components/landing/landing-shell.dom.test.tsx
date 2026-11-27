import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { type ComponentProps } from "react";

const mocks = rs.hoisted(() => ({
  pathname: "/",
  push: rs.fn(),
  refresh: rs.fn(),
  resolvedTheme: "light" as "light" | "dark",
  setTheme: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));

rs.mock("next/link", () => ({
  default: (props: ComponentProps<"a">) => <a {...props} />,
}));

rs.mock("next-themes", () => ({
  useTheme: () => ({
    resolvedTheme: mocks.resolvedTheme,
    setTheme: mocks.setTheme,
  }),
}));

import {
  ANNOUNCEMENT_BANNER_STORAGE_KEY,
  AnnouncementBanner,
} from "@/components/landing/announcement-banner";
import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { LanguageSwitch } from "@/components/landing/language-switch";
import { ThemeToggle } from "@/components/landing/theme-toggle";
import {
  LandingLocaleProvider,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";

function clearLocaleCookie() {
  document.cookie = "locale=; max-age=0; path=/";
}

function LocaleProbe({ fallback }: { fallback?: "en-US" | "zh-CN" }) {
  const { locale, docsLang, setLocale } = useOptionalLandingLocale(fallback);
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="docs-lang">{docsLang}</span>
      <span data-testid="has-setter">{setLocale ? "yes" : "no"}</span>
      {setLocale && (
        <button type="button" onClick={() => setLocale("zh-CN")}>
          Set ZH
        </button>
      )}
    </div>
  );
}

function ensureStorage(): Storage {
  if (
    typeof window.localStorage?.getItem === "function" &&
    typeof window.localStorage?.setItem === "function" &&
    typeof window.localStorage?.clear === "function"
  ) {
    return window.localStorage;
  }
  const store = new Map<string, string>();
  const memoryStorage: Storage = {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.get(key) ?? null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: memoryStorage,
  });
  return memoryStorage;
}

beforeEach(() => {
  mocks.pathname = "/";
  mocks.push.mockReset();
  mocks.refresh.mockReset();
  mocks.resolvedTheme = "light";
  mocks.setTheme.mockReset();
  ensureStorage().clear();
  clearLocaleCookie();
  window.history.replaceState(null, "", "/");
  document.documentElement.lang = "en-US";
  document.documentElement.style.removeProperty("--df-header-height");
  rs.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(null, { status: 204 }),
  );
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("LandingLocaleProvider & useOptionalLandingLocale", () => {
  it("falls back safely outside LandingLocaleProvider without throwing", () => {
    render(<LocaleProbe fallback="zh-CN" />);
    expect(screen.getByTestId("locale").textContent).toBe("zh-CN");
    expect(screen.getByTestId("docs-lang").textContent).toBe("zh");
    expect(screen.getByTestId("has-setter").textContent).toBe("no");
  });

  it("updates state, cookie, and <html lang> inside LandingLocaleProvider", () => {
    render(
      <LandingLocaleProvider initialLocale="en-US">
        <LocaleProbe />
      </LandingLocaleProvider>,
    );
    expect(screen.getByTestId("locale").textContent).toBe("en-US");
    expect(screen.getByTestId("docs-lang").textContent).toBe("en");
    expect(screen.getByTestId("has-setter").textContent).toBe("yes");

    fireEvent.click(screen.getByRole("button", { name: "Set ZH" }));
    expect(screen.getByTestId("locale").textContent).toBe("zh-CN");
    expect(screen.getByTestId("docs-lang").textContent).toBe("zh");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.cookie).toContain("locale=zh-CN");
  });
});

describe("ThemeToggle", () => {
  it("toggles between light and dark themes with accessible labels", () => {
    const { rerender } = render(<ThemeToggle />);
    const toDark = screen.getByRole("button", {
      name: "Switch to dark theme",
    });
    fireEvent.click(toDark);
    expect(mocks.setTheme).toHaveBeenCalledWith("dark");

    mocks.resolvedTheme = "dark";
    rerender(<ThemeToggle />);
    const toLight = screen.getByRole("button", {
      name: "Switch to light theme",
    });
    fireEvent.click(toLight);
    expect(mocks.setTheme).toHaveBeenCalledWith("light");
  });
});

describe("LanguageSwitch", () => {
  it("navigates across /en/docs and /zh/docs routes while preserving subpath", async () => {
    mocks.pathname = "/en/docs/application/quick-start";
    render(<LanguageSwitch locale="en-US" />);

    const trigger = screen.getByRole("button", { name: "Switch language" });
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);

    const zhItem = await screen.findByRole("menuitem", { name: /简体中文/ });
    fireEvent.click(zhItem);

    expect(mocks.push).toHaveBeenCalledWith("/zh/docs/application/quick-start");
    expect(document.cookie).toContain("locale=zh-CN");
  });

  it("updates ?lang= on /blog routes while preserving other query params and hash", async () => {
    mocks.pathname = "/blog/releases/2_0_rc";
    window.history.replaceState(
      null,
      "",
      "/blog/releases/2_0_rc?tab=notes&lang=zh#install",
    );

    render(<LanguageSwitch locale="zh-CN" />);

    const trigger = screen.getByRole("button", { name: "切换语言" });
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);

    const enItem = await screen.findByRole("menuitem", { name: /English/ });
    fireEvent.click(enItem);

    expect(mocks.push).toHaveBeenCalledWith(
      "/blog/releases/2_0_rc?tab=notes&lang=en#install",
    );
    expect(mocks.refresh).toHaveBeenCalled();
    expect(document.cookie).toContain("locale=en-US");
  });

  it("navigates on /blog when the selected locale matches header state but disagrees with ?lang=", async () => {
    mocks.pathname = "/blog/releases/2_0_rc";
    window.history.replaceState(
      null,
      "",
      "/blog/releases/2_0_rc?lang=zh#overview",
    );

    render(<LanguageSwitch locale="en-US" />);

    const trigger = screen.getByRole("button", { name: "Switch language" });
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);

    const enItem = await screen.findByRole("menuitem", { name: /English/ });
    fireEvent.click(enItem);

    expect(mocks.push).toHaveBeenCalledWith(
      "/blog/releases/2_0_rc?lang=en#overview",
    );
    expect(document.cookie).toContain("locale=en-US");
  });
});

describe("AnnouncementBanner", () => {
  it("dismisses persistently in localStorage and updates --df-header-height", async () => {
    const { unmount } = render(<AnnouncementBanner />);
    expect(
      document.documentElement.style.getPropertyValue("--df-header-height"),
    ).toBe("100px");

    fireEvent.click(
      screen.getByRole("button", { name: "Dismiss announcement" }),
    );
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Dismiss announcement" }),
      ).toBeNull();
    });
    expect(window.localStorage.getItem(ANNOUNCEMENT_BANNER_STORAGE_KEY)).toBe(
      "1",
    );
    expect(
      document.documentElement.style.getPropertyValue("--df-header-height"),
    ).toBe("64px");

    unmount();
    render(<AnnouncementBanner />);
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Dismiss announcement" }),
      ).toBeNull();
    });
  });
});

describe("Header & Footer shell", () => {
  it("renders announcement strip above main nav, grouped menus, search slot, and 2-tier editorial footer", () => {
    const { container } = render(
      <LandingLocaleProvider initialLocale="en-US">
        <Header
          showBanner
          search={<input aria-label="Search docs" placeholder="Search" />}
        />
        <Footer />
      </LandingLocaleProvider>,
    );

    expect(screen.getAllByText("DeerFlow").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("button", { name: "Product" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Integrations" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Developers" })).toBeTruthy();
    expect(screen.getByLabelText("Search docs")).toBeTruthy();

    const bannerRegion = screen.getByRole("region");
    const mainNav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(
      bannerRegion.compareDocumentPosition(mainNav) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    expect(
      screen.getByRole("button", { name: "Dismiss announcement" }),
    ).toBeTruthy();

    const getStarted = screen.getByRole("link", { name: /get started/i });
    expect(getStarted.getAttribute("href")).toBe("/workspace");

    const openWorkspace = screen.getByRole("link", { name: "Open Workspace" });
    expect(openWorkspace.getAttribute("href")).toBe("/workspace");

    const quickStart = screen.getByRole("link", { name: "Quick Start" });
    expect(quickStart.getAttribute("href")).toBe(
      "/en/docs/application/quick-start",
    );

    // 2-tier editorial footer: inline quick-start card, 4 columns, MIT + ByteDance attribution
    expect(container.textContent).toContain("git clone");
    expect(container.textContent).toContain("make config");
    expect(container.textContent).toContain("make install");
    expect(container.textContent).toContain("make dev");
    expect(screen.getByRole("heading", { name: "Product" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Capabilities" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Developers" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Community" })).toBeTruthy();
    expect(container.textContent).toContain("MIT License");
    expect(container.textContent).toContain("ByteDance");
  });

  it("copies the full config+install+dev quick-start command and renders zh-CN footer links when locale is passed", () => {
    const writeText = rs.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    const { rerender } = render(<Footer locale="en-US" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Copy quick-start commands" }),
    );
    expect(writeText).toHaveBeenCalledWith(
      "git clone https://github.com/bytedance/deer-flow.git && cd deer-flow && make config && make install && make dev",
    );

    rerender(<Footer locale="zh-CN" />);
    expect(screen.getByRole("heading", { name: "开源社区" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "完整文档" }).getAttribute("href"),
    ).toBe("/zh/docs");
    expect(
      screen.getByRole("link", { name: "进入工作区" }).getAttribute("href"),
    ).toBe("/workspace");
  });

  it("routes the mobile drawer Get Started CTA through /workspace", () => {
    render(<Header locale="en-US" />);
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));

    const links = screen.getAllByRole("link", { name: /get started/i });
    expect(links.length).toBeGreaterThanOrEqual(1);
    for (const link of links) {
      expect(link.getAttribute("href")).toBe("/workspace");
    }
  });
});
