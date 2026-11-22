import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { BrowserViewPanel } from "@/components/workspace/browser-view/browser-view-panel";
import { enUS } from "@/core/i18n/locales/en-US";
import type { Translations } from "@/core/i18n/locales/types";
import { zhCN } from "@/core/i18n/locales/zh-CN";

const { stream } = rs.hoisted(() => ({
  stream: {
    status: "closed" as "idle" | "connecting" | "open" | "closed",
    closedReason: "handshake_timeout" as
      | "handshake_timeout"
      | "connection_failed"
      | null,
    frameUrl: null as string | null,
    liveUrl: null,
    sendInput: rs.fn(),
  },
}));
let translations: Translations = enUS;

rs.mock("@/components/workspace/browser-view/use-browser-stream", () => ({
  useBrowserStream: () => stream,
}));
rs.mock("@/components/workspace/browser-view/context", () => ({
  useMaybeBrowserView: () => null,
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: translations }),
}));

afterEach(() => {
  cleanup();
  stream.status = "closed";
  stream.closedReason = "handshake_timeout";
  stream.frameUrl = null;
  translations = enUS;
});

for (const [locale, dictionary] of [
  ["en-US", enUS],
  ["zh-CN", zhCN],
] as const) {
  test.each([false, true])(
    `shows actionable ${locale} failures with a previous frame: %s`,
    (hasFrame) => {
      translations = dictionary;
      stream.frameUrl = hasFrame ? "data:image/jpeg;base64,AA==" : null;
      const view = render(<BrowserViewPanel threadId="thread-1" />);

      expect(screen.getByRole("status").textContent).toBe(
        dictionary.browserStream.handshakeTimeout,
      );
      expect(
        screen.getByRole("button", {
          name: dictionary.browserStream.disconnected,
        }),
      ).toBeTruthy();
      expect(screen.queryByText("Connecting to live browser…")).toBeNull();
      if (hasFrame) expect(screen.getByAltText("Browser view")).toBeTruthy();

      stream.closedReason = "connection_failed";
      view.rerender(<BrowserViewPanel threadId="thread-1" />);
      expect(screen.getByRole("status").textContent).toBe(
        dictionary.browserStream.connectionFailed,
      );

      stream.status = "connecting";
      stream.frameUrl = null;
      view.rerender(<BrowserViewPanel threadId="thread-1" />);
      expect(screen.getByRole("status").textContent).toBe(
        dictionary.browserStream.connectionFailed,
      );
      expect(
        screen.getByRole("button", {
          name: dictionary.browserStream.connecting,
        }),
      ).toBeTruthy();
      if (hasFrame) expect(screen.getByAltText("Browser view")).toBeTruthy();

      stream.status = "open";
      stream.closedReason = null;
      view.rerender(<BrowserViewPanel threadId="thread-1" />);
      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.getByRole("button", { name: "Live" })).toBeTruthy();
    },
  );
}

test("hides the failure notice when live control is turned off", () => {
  render(<BrowserViewPanel threadId="thread-1" />);
  expect(screen.getByRole("status")).toBeTruthy();
  fireEvent.click(screen.getByTitle("Stop live control"));
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByTitle("Take live control")).toBeTruthy();
});
