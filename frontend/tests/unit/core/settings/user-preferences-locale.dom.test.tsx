import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import type { Locale } from "@/core/i18n";
import { I18nProvider, useI18nContext } from "@/core/i18n/context";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";

const mocks = rs.hoisted(() => ({
  user: { id: "alice" },
  fetch: rs.fn(),
  server: {} as Record<string, unknown>,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));

let switchLocale: (locale: Locale) => void = () => undefined;

function LocaleSwitch() {
  const { setLocale } = useI18nContext();
  switchLocale = setLocale;
  return null;
}

function Workspace({ locale }: { locale: Locale }) {
  return (
    <I18nProvider initialLocale={locale}>
      <UserPreferencesBoundary>
        <LocaleSwitch />
      </UserPreferencesBoundary>
    </I18nProvider>
  );
}

function patches() {
  return mocks.fetch.mock.calls
    .filter(([, init]) => (init as RequestInit).method === "PATCH")
    .map(([, init]) => JSON.parse((init as RequestInit).body as string));
}

async function settle() {
  await act(async () => {
    for (let i = 0; i < 5; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  mocks.user = { id: "alice" };
  mocks.server = {};
  mocks.fetch
    .mockReset()
    .mockImplementation(async (_url: string, init: RequestInit) => {
      if (init.method === "PATCH") {
        mocks.server = {
          ...mocks.server,
          ...(JSON.parse(init.body as string) as Record<string, unknown>),
        };
        return Response.json(mocks.server);
      }
      return Response.json(mocks.server);
    });
});
afterEach(() => {
  cleanup();
});

describe("notification language follows the UI language", () => {
  it("saves the UI language once when the account's differs", async () => {
    mocks.server = { notification_enabled: true, locale: "en-US" };
    render(<Workspace locale="zh-CN" />);
    await waitFor(() => expect(patches()).toEqual([{ locale: "zh-CN" }]));
    await settle();
    expect(patches()).toEqual([{ locale: "zh-CN" }]);
  });

  it("saves it when an older account has no locale yet", async () => {
    mocks.server = { notification_enabled: false, locale: null };
    render(<Workspace locale="en-US" />);
    await waitFor(() => expect(patches()).toEqual([{ locale: "en-US" }]));
  });

  it("writes nothing to an older Gateway that does not know the field", async () => {
    // Its strict schema would reject the PATCH and hold every other edit.
    mocks.server = { notification_enabled: true };
    render(<Workspace locale="zh-CN" />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    act(() => switchLocale("en-US"));
    await settle();
    expect(patches()).toEqual([]);
  });

  it("does not write back another device's language on a later read", async () => {
    mocks.server = { locale: "zh-CN" };
    render(<Workspace locale="zh-CN" />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    await settle();
    // Another device switched the account to English.
    mocks.server = { locale: "en-US" };
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2));
    await settle();
    expect(patches()).toEqual([]);
    // Switching here still saves this device's choice.
    act(() => switchLocale("en-US"));
    act(() => switchLocale("zh-CN"));
    await waitFor(() => expect(patches()).toEqual([{ locale: "zh-CN" }]));
  });

  it("sends nothing when the account already matches", async () => {
    mocks.server = { locale: "zh-CN" };
    render(<Workspace locale="zh-CN" />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    await settle();
    expect(patches()).toEqual([]);
  });

  it("saves every language switch", async () => {
    mocks.server = { locale: "en-US" };
    render(<Workspace locale="en-US" />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
    await settle();
    expect(patches()).toEqual([]);
    act(() => switchLocale("zh-CN"));
    await waitFor(() => expect(patches()).toEqual([{ locale: "zh-CN" }]));
    act(() => switchLocale("en-US"));
    await waitFor(() =>
      expect(patches()).toEqual([{ locale: "zh-CN" }, { locale: "en-US" }]),
    );
  });

  it("never writes with auth disabled", async () => {
    mocks.user = { id: "default" };
    render(<Workspace locale="zh-CN" />);
    act(() => switchLocale("en-US"));
    await settle();
    expect(mocks.fetch).not.toHaveBeenCalled();
  });
});
