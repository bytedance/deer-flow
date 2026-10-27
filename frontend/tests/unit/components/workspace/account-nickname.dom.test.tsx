import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { AccountSettingsPage } from "@/components/workspace/settings/account-settings-page";
import { accountProfile } from "@/core/auth/profile";
import { I18nProvider } from "@/core/i18n/context";

const identity = rs.hoisted(() => ({
  user: { id: "alice", email: "alice@example.com", system_role: "user" },
  logout: rs.fn(),
}));
rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: () => identity }));
rs.mock("@/core/auth/profile", () => ({ accountProfile: rs.fn() }));
const request = rs.mocked(accountProfile);

beforeEach(() => {
  request.mockReset();
  identity.user = {
    id: "alice",
    email: "alice@example.com",
    system_role: "user",
  };
  document.cookie = "locale=en-US; path=/";
});
afterEach(cleanup);

function tree(client: QueryClient) {
  return (
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale="en-US">
        <AccountSettingsPage />
      </I18nProvider>
    </QueryClientProvider>
  );
}

it("loads, saves and clears a nickname in account settings", async () => {
  let nickname: string | null = "小林";
  request.mockImplementation(async (value) => {
    if (value !== undefined) nickname = value || null;
    return { nickname };
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(tree(client));
  const input = screen.getByLabelText<HTMLInputElement>("Nickname");
  await waitFor(() => expect(input.value).toBe("小林"));
  fireEvent.change(input, { target: { value: " 阿林 " } });
  fireEvent.click(screen.getByRole("button", { name: "Save nickname" }));
  await screen.findByRole("status");
  expect(request).toHaveBeenCalledWith("阿林");
  expect(input.value).toBe("阿林");
  view.unmount();
  render(tree(client));
  expect(screen.getByLabelText<HTMLInputElement>("Nickname").value).toBe(
    "阿林",
  );
  fireEvent.change(screen.getByLabelText("Nickname"), {
    target: { value: "" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save nickname" }));
  await screen.findByRole("status");
  expect(request).toHaveBeenCalledWith("");
  expect(client.getQueryData(["account-profile", "alice"])).toEqual({
    nickname: null,
  });
});

it("preserves failed drafts and discards them when the signed-in account changes", async () => {
  request.mockImplementation(async (value) => {
    if (value !== undefined) throw new Error("offline");
    return { nickname: identity.user.id === "alice" ? "小林" : "阿明" };
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(tree(client));
  const input = screen.getByLabelText<HTMLInputElement>("Nickname");
  await waitFor(() => expect(input.value).toBe("小林"));
  fireEvent.change(input, { target: { value: "草稿" } });
  fireEvent.click(screen.getByRole("button", { name: "Save nickname" }));
  await screen.findByRole("alert");
  expect(input.value).toBe("草稿");
  identity.user = { id: "bob", email: "bob@example.com", system_role: "user" };
  view.rerender(tree(client));
  await waitFor(() =>
    expect(screen.getByLabelText<HTMLInputElement>("Nickname").value).toBe(
      "阿明",
    ),
  );
  expect(screen.queryByRole("alert")).toBeNull();
});
