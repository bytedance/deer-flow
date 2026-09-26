import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ImageModelSettings } from "@/components/workspace/settings/image-model-settings";
import { enUS } from "@/core/i18n/locales/en-US";
import type * as ImageManagement from "@/core/models/image-management";
import {
  loadImageProfiles,
  saveImageProfile,
  testImageProfile,
  type ImageProfile,
} from "@/core/models/image-management";

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "admin", system_role: "admin" } }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/models/image-management", () => ({
  ...rs.requireActual<typeof ImageManagement>("@/core/models/image-management"),
  loadImageProfiles: rs.fn(),
  saveImageProfile: rs.fn(),
  testImageProfile: rs.fn(),
}));

const profile: ImageProfile = {
  name: "image-1",
  display_name: "Image One",
  provider: "openai",
  model: "image-model",
  base_url: "https://images.example/v1",
  size: null,
  enabled: true,
  source: "managed",
  has_api_key: true,
  revision: "v1",
  verified_generation: false,
  verified_edit: false,
};

beforeEach(() => {
  rs.mocked(loadImageProfiles).mockResolvedValue({
    profiles: [profile],
    status: {
      status: "configured_unverified",
      source: "managed",
      provider: "openai",
      model: "image-model",
      has_api_key: true,
      supports_generation: false,
      supports_edit: false,
    },
  });
  rs.mocked(saveImageProfile).mockResolvedValue(profile);
  rs.mocked(testImageProfile).mockResolvedValue({
    ok: true,
    message: "success",
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
  render(
    <QueryClientProvider client={client}>
      <ImageModelSettings />
    </QueryClientProvider>,
  );
}

test("editing preserves the image key and tests both required capabilities", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  const key = screen.getByLabelText<HTMLInputElement>("API Key");
  expect(key.value).toBe("");
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "Updated image model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveImageProfile).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveImageProfile).mock.calls[0]?.[0]).not.toHaveProperty(
    "api_key",
  );
  expect(rs.mocked(saveImageProfile).mock.calls[0]?.[1]).toBe("v1");

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "Test generation" }));
  await waitFor(() =>
    expect(testImageProfile).toHaveBeenCalledWith(
      "image-1",
      "v1",
      "generation",
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByRole<HTMLButtonElement>("button", {
        name: "Test reference editing",
      }).disabled,
    ).toBe(false),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Test reference editing" }),
  );
  await waitFor(() =>
    expect(testImageProfile).toHaveBeenCalledWith("image-1", "v1", "edit"),
  );
});
