import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  IncognitoNotices,
  IncognitoShell,
  IncognitoTitle,
} from "@/components/workspace/chats/incognito-frame";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

afterEach(cleanup);

describe("IncognitoShell", () => {
  test("labels the mode and frames the conversation", () => {
    render(
      <TooltipProvider>
        <IncognitoShell onEnd={rs.fn()}>
          <IncognitoTitle />
        </IncognitoShell>
      </TooltipProvider>,
    );

    expect(screen.getByText(enUS.incognito.label)).not.toBeNull();
    expect(screen.getByText(enUS.incognito.title)).not.toBeNull();
    // The conversation area is the light panel inside the dark surround.
    expect(
      screen
        .getByTestId("incognito-frame")
        .contains(screen.getByText(enUS.incognito.title)),
    ).toBe(true);
  });

  test("the × control ends the chat", () => {
    const onEnd = rs.fn();
    render(
      <TooltipProvider>
        <IncognitoShell onEnd={onEnd}>{null}</IncognitoShell>
      </TooltipProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: enUS.incognito.end }));

    expect(onEnd).toHaveBeenCalledTimes(1);
  });
});

describe("IncognitoNotices", () => {
  test("states the storage notice with the live idle lifetime", () => {
    render(<IncognitoNotices idleTtlSeconds={24 * 60 * 60} />);

    const text = screen.getByTestId("incognito-notices").textContent ?? "";
    expect(text).toContain(enUS.incognito.notices("1 day"));
  });

  test("does not invent a lifetime it could not read", () => {
    render(<IncognitoNotices idleTtlSeconds={null} />);

    expect(screen.getByTestId("incognito-notices").textContent).toContain(
      enUS.incognito.noticesUnknown,
    );
  });

  test("renders a shorter window in whole hours", () => {
    render(<IncognitoNotices idleTtlSeconds={3600} />);

    expect(screen.getByTestId("incognito-notices").textContent).toContain(
      enUS.incognito.notices("1 hour"),
    );
  });

  test("states the third-party boundary", () => {
    render(<IncognitoNotices idleTtlSeconds={null} />);

    expect(screen.getByTestId("incognito-notices").textContent).toContain(
      enUS.incognito.boundaryNotice,
    );
  });
});
