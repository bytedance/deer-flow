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
  setDefaultImageProfile,
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
  setDefaultImageProfile: rs.fn(),
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
  identity: "web-identity",
  selected: true,
  conflict: false,
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
  rs.mocked(setDefaultImageProfile).mockResolvedValue({
    revision: "saved-default",
  });
  rs.mocked(testImageProfile).mockResolvedValue({
    ok: true,
    message: "success",
  });
});

test("shows which image profile is selected when server and web profiles coexist", async () => {
  rs.mocked(loadImageProfiles).mockResolvedValue({
    profiles: [
      {
        ...profile,
        conflict: false,
      },
      {
        ...profile,
        name: "server-config",
        display_name: "Server configuration",
        source: "config",
        provider: "gemini",
        model: "server-image",
        revision: undefined,
        selected: false,
        conflict: false,
      },
    ],
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

  mount();

  expect(await screen.findByText(/Used for new image requests/)).toBeTruthy();
  expect(screen.getByText(/Overrides server configuration/)).toBeTruthy();
  expect(screen.getByText("Not used for new image requests")).toBeTruthy();
});

test("shows an inline-chat choice when a new server image model conflicts", async () => {
  rs.mocked(loadImageProfiles).mockResolvedValue({
    profiles: [
      { ...profile, selected: false, conflict: true },
      {
        ...profile,
        name: "server-config",
        display_name: "Server configuration",
        source: "config",
        provider: "gemini",
        model: "server-image",
        revision: undefined,
        selected: false,
        conflict: true,
      },
    ],
    status: {
      status: "configured_unverified",
      source: "managed",
      provider: "openai",
      model: "image-model",
      has_api_key: true,
      supports_generation: false,
      supports_edit: false,
      choice_required: true,
    },
  });

  mount();
  expect(
    (await screen.findAllByText("Choose in chat before generating an image"))
      .length,
  ).toBeGreaterThan(0);
  expect(screen.queryByText("Used for new image requests")).toBeNull();
});

test("setting the server model as default marks its card and persists the choice", async () => {
  const server: ImageProfile = {
    ...profile,
    name: "server-config",
    display_name: "Server configuration",
    source: "config",
    identity: "server-identity",
    provider: "gemini",
    model: "server-image",
    revision: undefined,
    selected: false,
    conflict: true,
  };
  const status = {
    status: "configured_unverified" as const,
    source: "managed" as const,
    provider: "openai" as const,
    model: "image-model",
    has_api_key: true,
    supports_generation: false,
    supports_edit: false,
    choice_required: true,
    default_revision: null,
  };
  rs.mocked(loadImageProfiles)
    .mockResolvedValueOnce({
      profiles: [{ ...profile, selected: false, conflict: true }, server],
      status,
    })
    .mockResolvedValue({
      profiles: [
        { ...profile, selected: false, conflict: false },
        { ...server, selected: true, conflict: false },
      ],
      status: {
        ...status,
        source: "sandbox_environment",
        choice_required: false,
        default_revision: "saved-default",
        default_active: true,
      },
    });

  mount();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Use Server configuration as default",
    }),
  );
  await waitFor(() =>
    expect(setDefaultImageProfile).toHaveBeenCalledWith(
      "sandbox_environment",
      "server-identity",
      null,
    ),
  );
  expect(
    await screen.findByLabelText("Default image model: Server configuration"),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", {
      name: "Use Server configuration as default",
    }),
  ).toBeNull();
  expect(
    screen.queryByText("Choose in chat before generating an image"),
  ).toBeNull();
});

test("can switch the saved default back to the enabled web model", async () => {
  rs.mocked(loadImageProfiles).mockResolvedValue({
    profiles: [
      {
        ...profile,
        selected: false,
        conflict: false,
        identity: "web-identity",
      },
    ],
    status: {
      status: "configured_unverified",
      source: "sandbox_environment",
      provider: "gemini",
      model: "server-image",
      has_api_key: true,
      supports_generation: false,
      supports_edit: false,
      default_revision: "old-default",
    },
  });
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Use Image One as default" }),
  );
  await waitFor(() =>
    expect(setDefaultImageProfile).toHaveBeenCalledWith(
      "managed",
      "web-identity",
      "old-default",
    ),
  );
});

test("can persist a web model that was selected automatically", async () => {
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Use Image One as default" }),
  );
  await waitFor(() =>
    expect(setDefaultImageProfile).toHaveBeenCalledWith(
      "managed",
      "web-identity",
      null,
    ),
  );
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
