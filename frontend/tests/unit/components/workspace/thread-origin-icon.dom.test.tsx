import { afterEach, describe, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import {
  ThreadChannelIcon,
  ThreadOriginIcon,
  ThreadUnreadDot,
} from "@/components/workspace/thread-channel-source";
import type { Locale } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import type { ThreadOrigin } from "@/core/threads/origin";

import { expectNoRawIdentifiers } from "../../helpers/readable";

afterEach(() => {
  cleanup();
  document.cookie = "locale=; max-age=0; path=/";
});

/** `useI18n` adopts the locale cookie on mount, so set both. */
function renderIn(locale: Locale, node: React.ReactNode) {
  document.cookie = `locale=${locale}; path=/`;
  return render(<I18nProvider initialLocale={locale}>{node}</I18nProvider>);
}

const CASES: Array<{
  origin: ThreadOrigin;
  en: string;
  zh: string;
  svgClass?: string;
}> = [
  {
    origin: { kind: "schedule" },
    en: "Scheduled run",
    zh: "定时运行",
    svgClass: "lucide-clock-3",
  },
  {
    origin: { kind: "im_channel", provider: "feishu" },
    en: "From Feishu",
    zh: "来自飞书",
  },
  {
    origin: { kind: "im_channel", provider: "wecom" },
    en: "From WeCom",
    zh: "来自企业微信",
  },
  {
    origin: { kind: "im_channel", provider: "slack" },
    en: "From Slack",
    zh: "来自 Slack",
  },
  {
    origin: { kind: "github", provider: "github" },
    en: "From GitHub",
    zh: "来自 GitHub",
  },
  {
    origin: { kind: "extension", namespace: "acme.tools" },
    en: "From an extension",
    zh: "来自扩展",
    svgClass: "lucide-puzzle",
  },
];

describe("ThreadOriginIcon", () => {
  for (const { origin, en, zh, svgClass } of CASES) {
    for (const [locale, label] of [
      ["en-US", en],
      ["zh-CN", zh],
    ] as const) {
      test(`${origin.kind}${"provider" in origin ? `/${origin.provider}` : ""} → "${label}" (${locale})`, () => {
        renderIn(locale, <ThreadOriginIcon origin={origin} />);
        const icon = screen.getByRole("img", { name: label });
        expect(icon.getAttribute("title")).toBe(label);
        expect(icon.getAttribute("data-origin-kind")).toBe(origin.kind);
        const svg = icon.querySelector("svg");
        expect(svg).not.toBeNull();
        expect(svg!.getAttribute("aria-hidden")).toBe("true");
        if (svgClass) {
          expect(svg!.getAttribute("class")).toContain(svgClass);
        }
        expectNoRawIdentifiers(label);
      });
    }
  }

  test("the GitHub origin uses the GitHub mark, not the generic chat bubble", () => {
    renderIn(
      "en-US",
      <ThreadOriginIcon origin={{ kind: "github", provider: "github" }} />,
    );
    const svg = screen.getByRole("img", {
      name: "From GitHub",
    }).firstElementChild!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 16 16");
    expect(svg.getAttribute("class")).not.toContain("lucide-message-circle");
  });

  test("an unknown provider keeps its raw name only as the fallback label", () => {
    renderIn(
      "zh-CN",
      <ThreadOriginIcon origin={{ kind: "im_channel", provider: "matrix" }} />,
    );
    expect(screen.getByRole("img", { name: "来自 matrix" })).not.toBeNull();
  });

  test("null and MCP notification origins render nothing", () => {
    const { container } = renderIn(
      "en-US",
      <>
        <ThreadOriginIcon origin={null} />
        <ThreadOriginIcon origin={{ kind: "mcp_notification" }} />
      </>,
    );
    expect(container.innerHTML).toBe("");
  });

  test("ThreadChannelIcon is the origin icon of its provider, localized", () => {
    renderIn(
      "zh-CN",
      <ThreadChannelIcon
        source={{ type: "im_channel", provider: "dingtalk", label: "钉钉" }}
      />,
    );
    const icon = screen.getByRole("img", { name: "来自钉钉" });
    expect(icon.getAttribute("data-origin-kind")).toBe("im_channel");
    expect(screen.queryByText(/channel/)).toBeNull();
  });
});

describe("ThreadUnreadDot", () => {
  test("is a decorative dot with sr-only text in both locales", () => {
    for (const [locale, text] of [
      ["en-US", "Unread"],
      ["zh-CN", "未读"],
    ] as const) {
      const { unmount } = renderIn(locale, <ThreadUnreadDot />);
      const dot = screen.getByTestId("thread-unread-dot");
      expect(dot.getAttribute("title")).toBe(text);
      expect(dot.querySelector('[aria-hidden="true"]')).not.toBeNull();
      expect(dot.querySelector(".sr-only")?.textContent).toBe(text);
      unmount();
    }
  });
});
