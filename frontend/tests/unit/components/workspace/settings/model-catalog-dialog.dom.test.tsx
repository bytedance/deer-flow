import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ModelCatalogDialog } from "@/components/workspace/settings/model-catalog-dialog";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  discoverModels,
  importCatalogModel,
  type ManagedModel,
} from "@/core/models/management";

rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/models/management", () => ({
  discoverModels: rs.fn(),
  importCatalogModel: rs.fn(),
}));
const discover = rs.mocked(discoverModels),
  add = rs.mocked(importCatalogModel);
const saved = rs.fn().mockResolvedValue(undefined);
const props = {
  models: [],
  providers: [
    {
      id: "openai",
      display_name: "OpenAI",
      requires_api_key: true,
      custom_endpoint: false,
    },
  ],
  close: rs.fn(),
  saved,
};
beforeEach(() => {
  rs.clearAllMocks();
  discover.mockResolvedValue({
    models: [
      { id: "good", configured: false },
      { id: "bad", configured: false },
      { id: "old", configured: true },
    ],
    truncated: false,
  });
});
afterEach(cleanup);
async function load() {
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "only-in-draft" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Fetch models" }));
  await screen.findByText("good");
}
it("fetches without saving, filters selection, keeps partial failures retryable", async () => {
  add.mockImplementation(async (_connection, id) =>
    id === "bad"
      ? { status: "failed", message: "tool_call_missing" }
      : { status: "saved", model: { name: "saved" } as never },
  );
  render(<ModelCatalogDialog {...props} />);
  await load();
  expect(add).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("API Key")?.closest("details")?.open).toBe(
    false,
  );
  expect(screen.getByRole("checkbox", { name: /old/ })).toHaveProperty(
    "disabled",
    true,
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Search models…" }), {
    target: { value: "good" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Select visible" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Search models…" }), {
    target: { value: "" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: "bad" }));
  fireEvent.click(screen.getByRole("button", { name: "Test and add (2)" }));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(add.mock.calls.map((call) => call[1])).toEqual(["good", "bad"]);
  expect(
    screen.getByText(enUS.settings.models.tool_call_missing),
  ).toBeDefined();
  expect(
    screen.getByRole("button", { name: "Test and add (1)" }),
  ).toHaveProperty("disabled", false);
});
it("clears catalog and selected models after a credential edit", async () => {
  render(<ModelCatalogDialog {...props} />);
  await load();
  fireEvent.click(screen.getByRole("button", { name: "Select visible" }));
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "other-key" },
  });
  expect(screen.queryByText("good")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Test and add (0)" }),
  ).toHaveProperty("disabled", true);
});
it("aborts an unmounted discovery and ignores its late response", async () => {
  let finish!: (value: Awaited<ReturnType<typeof discoverModels>>) => void;
  discover.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(<ModelCatalogDialog {...props} />);
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "test" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Fetch models" }));
  const signal = discover.mock.calls[0]![1]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  finish({ models: [{ id: "late", configured: false }], truncated: false });
  expect(add).not.toHaveBeenCalled();
});

it("stopping an import refreshes committed results and leaves the uncertain item retryable", async () => {
  add.mockImplementation(
    (_connection, _id, signal) =>
      new Promise((_resolve, reject) => {
        signal!.addEventListener("abort", () =>
          reject(new DOMException("Cancelled", "AbortError")),
        );
      }),
  );
  render(<ModelCatalogDialog {...props} />);
  await load();
  fireEvent.click(screen.getByRole("checkbox", { name: "good" }));
  fireEvent.click(screen.getByRole("button", { name: "Test and add (1)" }));
  await waitFor(() => expect(add).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await screen.findByText(enUS.settings.models.importStopped);
  expect(screen.getByText(enUS.settings.models.importUncertain)).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "Test and add (1)" }),
  ).toHaveProperty("disabled", false);
  expect(saved).toHaveBeenCalledTimes(1);
});

it("fills a custom connection in display order without losing the key", async () => {
  render(
    <ModelCatalogDialog
      {...props}
      providers={[
        ...props.providers,
        {
          id: "openai-compatible",
          display_name: "Custom",
          requires_api_key: false,
          custom_endpoint: true,
        },
      ]}
    />,
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Provider" }), {
    target: { value: "openai-compatible" },
  });
  const endpoint = screen.getByLabelText(enUS.settings.models.endpoint);
  const key = screen.getByLabelText("API Key");
  const inputs = Array.from(document.querySelectorAll("input"));
  expect(inputs.indexOf(endpoint as HTMLInputElement)).toBeLessThan(
    inputs.indexOf(key as HTMLInputElement),
  );
  fireEvent.change(endpoint, {
    target: { value: "https://custom.example/v1" },
  });
  fireEvent.change(key, { target: { value: "custom-key" } });
  fireEvent.click(screen.getByRole("button", { name: "Fetch models" }));
  await waitFor(() => expect(discover).toHaveBeenCalled());
  expect(discover.mock.calls[0]![0]).toMatchObject({
    provider: "openai-compatible",
    base_url: "https://custom.example/v1",
    api_key: "custom-key",
  });
  fireEvent.change(endpoint, { target: { value: "https://other.example/v1" } });
  expect((key as HTMLInputElement).value).toBe("");
});

it("reuses a saved connection only until its destination changes", async () => {
  const model: ManagedModel = {
    name: "saved-custom",
    display_name: "Saved custom",
    model: "old",
    provider: "openai-compatible",
    base_url: "https://saved.example/v1",
    enabled: true,
    supports_vision: null,
    context_window: null,
    max_tokens: null,
    revision: "rev-1",
    source: "managed",
    has_api_key: true,
  };
  render(
    <ModelCatalogDialog
      {...props}
      models={[model]}
      providers={[
        ...props.providers,
        {
          id: "openai-compatible",
          display_name: "Custom",
          requires_api_key: false,
          custom_endpoint: true,
        },
      ]}
    />,
  );
  fireEvent.change(
    screen.getByLabelText(enUS.settings.models.savedConnection),
    { target: { value: model.name } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Fetch models" }));
  await screen.findByText("good");
  expect(discover.mock.calls[0]![0]).toEqual({
    provider: model.provider,
    base_url: model.base_url,
    saved_model_name: model.name,
    expected_revision: model.revision,
  });
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "replacement-key" },
  });
  fireEvent.change(screen.getByLabelText(enUS.settings.models.endpoint), {
    target: { value: "https://new.example/v1" },
  });
  expect(screen.getByLabelText("API Key")).toHaveProperty("value", "");
  expect(
    screen.getByLabelText(enUS.settings.models.savedConnection),
  ).toHaveProperty("value", "");
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "new-destination-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Fetch models" }));
  await waitFor(() => expect(discover).toHaveBeenCalledTimes(2));
  expect(discover.mock.calls[1]![0]).toEqual({
    provider: model.provider,
    base_url: "https://new.example/v1",
    api_key: "new-destination-key",
  });
});
