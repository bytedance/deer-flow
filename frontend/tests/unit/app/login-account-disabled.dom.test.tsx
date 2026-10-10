import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import { useAuth } from "@/core/auth/AuthProvider";
import type * as Setup from "@/core/auth/setup";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/components/ui/flickering-grid", () => ({
  FlickeringGrid: () => null,
}));
rs.mock("@/core/auth/setup", () => ({
  ...(rs.requireActual<typeof Setup>("@/core/auth/setup") as object),
  fetchSetupStatus: rs.fn(async () => ({
    needs_setup: false,
    registration_enabled: true,
  })),
}));

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

beforeEach(() => {
  rs.mocked(useAuth).mockReturnValue({
    isAuthenticated: false,
  } as ReturnType<typeof useAuth>);
  globalThis.fetch = rs.fn(async () =>
    jsonResponse({ providers: [] }),
  ) as unknown as typeof globalThis.fetch;
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(enUS.login.email), {
    target: { value: "suspended@example.com" },
  });
  fireEvent.change(screen.getByLabelText<HTMLInputElement>(
    enUS.login.password,
  ), {
    target: { value: "correct-horse-battery" },
  });
  fireEvent.click(screen.getByRole("button", { name: enUS.login.signIn }));
}

test("an account_disabled rejection shows the localized reason", async () => {
  globalThis.fetch = rs.fn(async () =>
    jsonResponse(
      { detail: { code: "account_disabled", message: "Account disabled" } },
      401,
    ),
  ) as unknown as typeof globalThis.fetch;
  render(<LoginPage />);

  await waitFor(() => screen.getByRole("button", { name: enUS.login.signIn }));
  fillAndSubmit();

  expect(
    await screen.findByText(enUS.login.errors.account_disabled),
  ).toBeTruthy();
});

test("other rejections keep showing the backend message", async () => {
  globalThis.fetch = rs.fn(async () =>
    jsonResponse(
      {
        detail: {
          code: "invalid_credentials",
          message: "Incorrect email or password",
        },
      },
      401,
    ),
  ) as unknown as typeof globalThis.fetch;
  render(<LoginPage />);

  await waitFor(() => screen.getByRole("button", { name: enUS.login.signIn }));
  fillAndSubmit();

  expect(await screen.findByText("Incorrect email or password")).toBeTruthy();
});
