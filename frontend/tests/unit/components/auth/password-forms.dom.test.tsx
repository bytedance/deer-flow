import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createContext } from "react";

import LoginPage from "@/app/(auth)/login/page";
import SetupPage from "@/app/(auth)/setup/page";
import { enUS } from "@/core/i18n/locales/en-US";

const router = { push: rs.fn(), replace: rs.fn() };
type Mode = "login" | "register" | "initialize" | "change-password";
const modes: Mode[] = ["login", "register", "initialize", "change-password"];
let mode: Mode = "login";

rs.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/components/ui/flickering-grid", () => ({
  FlickeringGrid: () => null,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  AuthDisabledContext: createContext(false),
  useAuth: () => ({
    isAuthenticated: mode === "change-password",
    user: mode === "change-password" ? { needs_setup: true } : null,
  }),
}));
rs.mock("@/core/api/fetcher", () => ({ getCsrfHeaders: () => ({}) }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
const fetchMock = rs.fn<typeof fetch>();
const posts = () =>
  fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");

beforeEach(() => {
  mode = "login";
  localStorage.clear();
  router.push.mockReset();
  router.replace.mockReset();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    if (input === "/api/v1/auth/setup-status") {
      return jsonResponse({
        needs_setup: mode === "initialize",
        registration_enabled: true,
      });
    }
    if (input === "/api/v1/auth/providers")
      return jsonResponse({ providers: [] });
    if (init?.method === "POST") return jsonResponse({});
    throw new Error("Unexpected auth request");
  });
  rs.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  rs.unstubAllGlobals();
});

async function mountForm(
  nextMode: Mode,
  email: string,
  password = "  secret9  ",
) {
  mode = nextMode;
  if (mode === "login") {
    localStorage.setItem("deerflow.auth.remembered_email", email);
  }
  render(
    mode === "login" || mode === "register" ? <LoginPage /> : <SetupPage />,
  );
  if (mode === "register") {
    fireEvent.click(
      await screen.findByRole("button", { name: enUS.login.noAccountSignUp }),
    );
  }
  const addressInput =
    mode === "change-password"
      ? await screen.findByPlaceholderText("Your email")
      : await screen.findByLabelText("Email");
  // Preserve a remembered raw value in React state; type=email sanitizes
  // typed outer spaces before onChange and would hide the submission bug.
  if (mode !== "login")
    fireEvent.change(addressInput, { target: { value: email } });
  const passwordInput =
    mode === "change-password"
      ? screen.getByPlaceholderText("New password")
      : screen.getByLabelText("Password");
  fireEvent.change(passwordInput, { target: { value: password } });
  if (mode === "initialize" || mode === "change-password") {
    fireEvent.change(
      mode === "initialize"
        ? screen.getByLabelText("Confirm Password")
        : screen.getByPlaceholderText("Confirm new password"),
      { target: { value: password } },
    );
  }
  if (mode === "change-password") {
    fireEvent.change(screen.getByPlaceholderText("Current password"), {
      target: { value: "current-password" },
    });
  }
  const form = addressInput.closest("form")!;
  expect(form.noValidate).toBe(true);
  return form;
}

test.each(modes)(
  "%s submits the same trimmed Unicode address it validates",
  async (formMode) => {
    const password = "  safe  ";
    const form = await mountForm(formMode, "  用户@example.com  ", password);
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/workspace"));
    expect(posts()).toHaveLength(1);
    const [endpoint, request] = posts()[0]!;
    if (formMode === "login") {
      expect(endpoint).toBe("/api/v1/auth/login/local");
      expect(request!.body).toBeInstanceOf(URLSearchParams);
      const body = request!.body as URLSearchParams;
      expect(body.get("username")).toBe("用户@example.com");
      expect(body.get("password")).toBe(password);
      expect(localStorage.getItem("deerflow.auth.remembered_email")).toBe(
        "用户@example.com",
      );
    } else {
      expect(typeof request!.body).toBe("string");
      const body = JSON.parse(request!.body as string) as Record<
        string,
        unknown
      >;
      expect(endpoint).toBe(
        `/api/v1/auth/${formMode === "register" ? "register" : formMode === "initialize" ? "initialize" : "change-password"}`,
      );
      expect(body[formMode === "change-password" ? "new_email" : "email"]).toBe(
        "用户@example.com",
      );
      expect(
        body[formMode === "change-password" ? "new_password" : "password"],
      ).toBe(password);
    }
  },
);

const invalidPasswords: [Mode, string][] = modes.flatMap((formMode) => [
  [formMode, ""],
  [formMode, formMode === "login" ? "12345" : "1234567"],
]);
test.each(invalidPasswords)(
  "%s blocks password %j before making a request",
  async (formMode, password) => {
    const form = await mountForm(formMode, "用户@example.com", password);
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(posts()).toHaveLength(0);
    expect(screen.getByText(/Password must be at least/)).toBeTruthy();
    expect(router.push).not.toHaveBeenCalled();
  },
);

test.each(modes)(
  "%s rejects malformed email before making a request",
  async (formMode) => {
    const form = await mountForm(formMode, "not-an-email");
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(posts()).toHaveLength(0);
    expect(screen.getByText(/Please enter a valid email address/)).toBeTruthy();
  },
);

test("login keeps supporting a six-character password", async () => {
  const form = await mountForm("login", "用户@example.com", "secret");
  await act(async () => {
    fireEvent.submit(form);
  });
  await waitFor(() => expect(router.push).toHaveBeenCalledWith("/workspace"));
  expect(posts()).toHaveLength(1);
});

test("password change requires the current password before making a request", async () => {
  const form = await mountForm("change-password", "用户@example.com");
  fireEvent.change(screen.getByPlaceholderText("Current password"), {
    target: { value: "" },
  });
  await act(async () => {
    fireEvent.submit(form);
  });
  expect(posts()).toHaveLength(0);
  expect(screen.getByText("Please enter your current password")).toBeTruthy();
});

test.each(["initialize", "change-password"] as const)(
  "%s still rejects a password confirmation mismatch",
  async (formMode) => {
    const form = await mountForm(formMode, "用户@example.com");
    fireEvent.change(
      formMode === "initialize"
        ? screen.getByLabelText("Confirm Password")
        : screen.getByPlaceholderText("Confirm new password"),
      { target: { value: "different-password" } },
    );
    await act(async () => {
      fireEvent.submit(form);
    });
    expect(posts()).toHaveLength(0);
    expect(screen.getByText("Passwords do not match")).toBeTruthy();
  },
);
