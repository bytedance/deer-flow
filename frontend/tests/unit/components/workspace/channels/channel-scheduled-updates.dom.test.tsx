import { afterEach, describe, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { ChannelScheduledUpdates } from "@/components/workspace/channels/channel-scheduled-updates";
import type { Locale } from "@/core/i18n";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

afterEach(cleanup);

function renderIn(locale: Locale, proactive: boolean | undefined) {
  return render(
    <I18nContext.Provider
      value={{
        locale,
        setLocale: () => undefined,
        t: locale === "zh-CN" ? zhCN : enUS,
      }}
    >
      <ChannelScheduledUpdates
        provider={{ proactive_notifications: proactive }}
      />
    </I18nContext.Provider>,
  );
}

describe("ChannelScheduledUpdates", () => {
  for (const [locale, supported, unsupported] of [
    [
      "en-US",
      "Scheduled task updates: sent here",
      "Scheduled task updates: not available for this app yet",
    ],
    ["zh-CN", "定时任务通知：会发送到这里", "定时任务通知：此应用暂不支持"],
  ] as const) {
    test(`an app with proactive push says updates are sent here (${locale})`, () => {
      renderIn(locale, true);
      const line = screen.getByTestId("channel-scheduled-updates");
      expect(line.textContent).toBe(supported);
      expect(line.getAttribute("data-supported")).toBe("true");
      expect(line.querySelector("svg")?.getAttribute("aria-hidden")).toBe(
        "true",
      );
    });

    test(`an app without it says so (${locale})`, () => {
      renderIn(locale, false);
      const line = screen.getByTestId("channel-scheduled-updates");
      expect(line.textContent).toBe(unsupported);
      expect(line.getAttribute("data-supported")).toBe("false");
    });
  }

  test("an older backend that does not report the capability shows nothing", () => {
    renderIn("en-US", undefined);
    expect(screen.queryByTestId("channel-scheduled-updates")).toBeNull();
  });
});
