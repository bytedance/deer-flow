import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { IncognitoEntry } from "@/components/workspace/chats/incognito-entry";
import { enUS } from "@/core/i18n/locales/en-US";

const mocks = rs.hoisted(() => ({
  enabled: true,
  staticOnly: "false",
}));

rs.mock("@/core/features/hooks", () => ({
  useIncognitoFeature: () => ({
    enabled: mocks.enabled,
    idleTtlSeconds: 86400,
    isLoading: false,
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));
rs.mock("@/env", () => ({
  env: {
    get NEXT_PUBLIC_STATIC_WEBSITE_ONLY() {
      return mocks.staticOnly;
    },
  },
}));

function renderEntry({ isNewThread = true }: { isNewThread?: boolean } = {}) {
  return render(
    <TooltipProvider>
      <IncognitoEntry isNewThread={isNewThread} />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  mocks.enabled = true;
  mocks.staticOnly = "false";
});

afterEach(cleanup);

describe("incognito entry", () => {
  test("offers a ghost entry to a new incognito chat", () => {
    renderEntry();

    const link = screen.getByRole("link", { name: enUS.incognito.entry });
    expect(link.getAttribute("href")).toBe(
      "/workspace/chats/new?incognito=true",
    );
  });

  test("stays out once the chat has been saved", () => {
    renderEntry({ isNewThread: false });

    expect(
      screen.queryByRole("link", { name: enUS.incognito.entry }),
    ).toBeNull();
  });

  test("stays out when the operator disables incognito chats", () => {
    mocks.enabled = false;
    renderEntry();

    expect(
      screen.queryByRole("link", { name: enUS.incognito.entry }),
    ).toBeNull();
  });

  test("stays out in a static demo without a Gateway", () => {
    mocks.staticOnly = "true";
    renderEntry();

    expect(
      screen.queryByRole("link", { name: enUS.incognito.entry }),
    ).toBeNull();
  });
});
