import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { IncognitoFrame } from "@/components/workspace/chats/incognito-frame";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

afterEach(cleanup);

describe("IncognitoFrame", () => {
  test("states both notices and the live idle lifetime", () => {
    render(<IncognitoFrame idleTtlSeconds={24 * 60 * 60} onEnd={rs.fn()} />);

    const text = screen.getByTestId("incognito-frame").textContent ?? "";
    expect(text).toContain(enUS.incognito.privacyNotice);
    expect(text).toContain(
      "It is deleted automatically after 1 day of inactivity.",
    );
  });

  test("does not invent a lifetime it could not read", () => {
    render(<IncognitoFrame idleTtlSeconds={null} onEnd={rs.fn()} />);

    const text = screen.getByTestId("incognito-frame").textContent ?? "";
    expect(text).toBe(
      `${enUS.incognito.privacyNotice}${enUS.incognito.lifetimeUnknown}`,
    );
  });

  test("renders a shorter window in whole hours", () => {
    render(<IncognitoFrame idleTtlSeconds={3600} onEnd={rs.fn()} />);

    expect(screen.getByTestId("incognito-frame").textContent).toContain(
      "It is deleted automatically after 1 hour of inactivity.",
    );
  });

  test("the × control ends the chat", () => {
    const onEnd = rs.fn();
    render(<IncognitoFrame idleTtlSeconds={3600} onEnd={onEnd} />);

    fireEvent.click(screen.getByRole("button", { name: enUS.incognito.end }));

    expect(onEnd).toHaveBeenCalledTimes(1);
  });
});
