import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ModelSettingsPage } from "@/components/workspace/settings/model-settings-page";
import { useAuth } from "@/core/auth/AuthProvider";
import { enUS } from "@/core/i18n/locales/en-US";
import type * as Management from "@/core/models/management";
import {
  loadManagedModels,
  modelDraft,
  saveManagedModel,
  testManagedModel,
  type ManagedModel,
} from "@/core/models/management";

rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/models/management", () => ({
  ...rs.requireActual<typeof Management>("@/core/models/management"),
  loadManagedModels: rs.fn(),
  saveManagedModel: rs.fn(),
  testManagedModel: rs.fn(),
}));

const existing: ManagedModel = {
  ...modelDraft(),
  name: "custom",
  model: "test",
  base_url: "https://example.com/v1",
  display_name: "Custom",
  source: "managed",
  has_api_key: true,
  revision: "v1",
};
const auth = (role: "admin" | "user") =>
  ({ user: { id: "admin-id", system_role: role } }) as ReturnType<
    typeof useAuth
  >;

beforeEach(() => {
  rs.mocked(useAuth).mockReturnValue(auth("admin"));
  rs.mocked(loadManagedModels).mockResolvedValue({ models: [existing] });
  rs.mocked(saveManagedModel).mockResolvedValue({
    ...existing,
    revision: "v2",
  });
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["models"], { models: [] });
  render(
    <QueryClientProvider client={client}>
      <ModelSettingsPage />
    </QueryClientProvider>,
  );
  return client;
}

test("non-admin cannot load credentials configuration or add models", () => {
  rs.mocked(useAuth).mockReturnValue(auth("user"));
  mount();
  expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
  expect(loadManagedModels).not.toHaveBeenCalled();
});

test("editing preserves saved key and refreshes chat catalog after saving", async () => {
  const client = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  const input = screen.getByLabelText<HTMLInputElement>("API Key");
  expect(input.value).toBe("");
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "Updated" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveManagedModel).mock.calls[0]?.[0]).toMatchObject({
    config: { display_name: "Updated" },
    expected_revision: "v1",
  });
  expect(
    rs.mocked(saveManagedModel).mock.calls[0]?.[0].config,
  ).not.toHaveProperty("api_key");
  await waitFor(() =>
    expect(client.getQueryState(["models"])?.isInvalidated).toBe(true),
  );
});

test("failed save keeps draft open and displays conflict", async () => {
  rs.mocked(saveManagedModel).mockRejectedValueOnce(
    new Error("Model changed; reload before saving"),
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.change(screen.getByLabelText<HTMLInputElement>("API Key"), {
    target: { value: "replacement" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(
    await screen.findByText("Model changed; reload before saving"),
  ).toBeTruthy();
  expect(screen.getByLabelText<HTMLInputElement>("API Key").value).toBe(
    "replacement",
  );
});

test("connection test never saves and supports explicit key removal", async () => {
  rs.mocked(testManagedModel).mockResolvedValueOnce({
    ok: true,
    message: "success",
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.click(screen.getByLabelText("Remove the saved API key"));
  fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  expect(await screen.findByText(enUS.settings.models.success)).toBeTruthy();
  expect(rs.mocked(testManagedModel).mock.calls[0]?.[0].config.api_key).toBe(
    "",
  );
  expect(saveManagedModel).not.toHaveBeenCalled();
});
