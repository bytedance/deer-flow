import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { AgentSettingsDialog } from "@/components/workspace/agents/agent-settings-dialog";
import type { Agent } from "@/core/agents";
import { enUS } from "@/core/i18n/locales/en-US";
import type { Model, ModelsResponse } from "@/core/models/types";

const { mutateAsync, loadModels } = rs.hoisted(() => ({
  mutateAsync: rs.fn().mockResolvedValue({}),
  loadModels: rs.fn<() => Promise<ModelsResponse>>(),
}));
rs.mock("@/core/agents", () => ({
  useAgentToolGroups: () => ({ toolGroups: [], isLoading: false, error: null }),
  useUpdateAgent: () => ({ mutateAsync, isPending: false }),
}));
rs.mock("@/core/models/api", () => ({ loadModels }));
rs.mock("@/core/features", () => ({
  useKnowledgeBaseEnabled: () => ({ scopeSelectionEnabled: false }),
}));
rs.mock("@/core/subagents", () => ({
  useSubagents: () => ({ subagents: [] }),
}));
rs.mock("@/core/capabilities/hooks", () => ({
  useCapabilityInstallations: () => ({
    data: { items: [], can_manage: false },
    isLoading: false,
    isError: false,
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("sonner", () => ({ toast: { success: rs.fn(), error: rs.fn() } }));

const reasoningModel: Model = {
  id: "reasoner",
  name: "reasoner",
  model: "reasoner",
  display_name: "Reasoner",
  supports_thinking: true,
  supports_reasoning_effort: true,
};
const plainModel: Model = {
  id: "plain",
  name: "plain",
  model: "plain",
  display_name: "Plain model",
};
const catalog: ModelsResponse = {
  models: [reasoningModel, plainModel],
  token_usage: { enabled: false },
};
const agent: Agent = {
  name: "reviewer",
  description: "",
  model: "reasoner",
  tool_groups: null,
  skills: null,
  thinking_enabled: false,
  reasoning_effort: "high",
};
const clients: QueryClient[] = [];

beforeEach(() => {
  loadModels.mockReset();
  loadModels.mockResolvedValue(catalog);
  rs.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(
    () => undefined,
  );
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  mutateAsync.mockClear();
  rs.restoreAllMocks();
});

function renderSettings(value: Agent = agent) {
  const client = new QueryClient();
  client.setQueryDefaults(["models"], { retryDelay: 0 });
  clients.push(client);
  const view = render(
    <AgentSettingsDialog agent={value} open onOpenChange={rs.fn()} />,
    {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return { ...view, client };
}

async function saveRequest() {
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "Rename only" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
  return (mutateAsync.mock.calls[0]![0] as { request: Record<string, unknown> })
    .request;
}

function expectReasoningOmitted(request: Record<string, unknown>) {
  expect(request).not.toHaveProperty("thinking_enabled");
  expect(request).not.toHaveProperty("reasoning_effort");
}

async function selectOption(label: string, name: string) {
  fireEvent.keyDown(screen.getByRole("combobox", { name: label }), {
    key: "ArrowDown",
  });
  fireEvent.click(await screen.findByRole("option", { name }));
}

describe("custom agent reasoning update isolation", () => {
  it("preserves saved reasoning while the initial model catalog is pending", async () => {
    loadModels.mockReturnValue(new Promise(() => undefined));
    renderSettings();
    const request = await saveRequest();
    expect(request.display_name).toBe("Rename only");
    expectReasoningOmitted(request);
  });

  it("preserves saved reasoning after the initial catalog request fails", async () => {
    loadModels.mockRejectedValue(new Error("Model catalog unavailable"));
    const { client } = renderSettings();
    await waitFor(() =>
      expect(client.getQueryState(["models"])?.status).toBe("error"),
    );
    expectReasoningOmitted(await saveRequest());
  });

  it("preserves saved reasoning when a successful catalog is empty", async () => {
    loadModels.mockResolvedValue({ ...catalog, models: [] });
    const { client } = renderSettings();
    await waitFor(() =>
      expect(client.getQueryState(["models"])?.status).toBe("success"),
    );
    expectReasoningOmitted(await saveRequest());
  });

  it.each(["pending", "failed", "empty"] as const)(
    "blocks a model switch with an unresolved %s catalog but allows reverting it",
    async (state) => {
      if (state === "pending") {
        loadModels.mockReturnValue(new Promise(() => undefined));
      } else if (state === "failed") {
        loadModels.mockRejectedValue(new Error("Model catalog unavailable"));
      } else {
        loadModels.mockResolvedValue({ ...catalog, models: [] });
      }
      const { client } = renderSettings();
      if (state !== "pending") {
        await waitFor(() =>
          expect(client.getQueryState(["models"])?.status).toBe(
            state === "failed" ? "error" : "success",
          ),
        );
      }
      await selectOption("Default model", "Use global default");
      const save = screen.getByRole("button", { name: "Save" });
      expect((save as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByRole("status").textContent).toContain(
        "Load the selected model before saving",
      );
      fireEvent.click(save);
      expect(mutateAsync).not.toHaveBeenCalled();

      await selectOption("Default model", "reasoner");
      expect((save as HTMLButtonElement).disabled).toBe(false);
      expectReasoningOmitted(await saveRequest());
    },
  );

  it("normalizes a global-default switch when the pending catalog resolves before saving", async () => {
    let resolveCatalog!: (value: ModelsResponse) => void;
    loadModels.mockReturnValue(
      new Promise((resolve) => {
        resolveCatalog = resolve;
      }),
    );
    const { client } = renderSettings();
    await selectOption("Default model", "Use global default");
    expect(client.getQueryState(["models"])?.status).toBe("pending");
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Save" }).disabled,
    ).toBe(true);

    await act(async () => {
      resolveCatalog({ ...catalog, models: [plainModel, reasoningModel] });
    });
    await waitFor(() =>
      expect(client.getQueryState(["models"])?.status).toBe("success"),
    );
    expect(await saveRequest()).toMatchObject({
      model: null,
      thinking_enabled: null,
      reasoning_effort: null,
    });
  });

  it.each(["reasoner", "missing", null])(
    "preserves unchanged reasoning for model %s after a successful catalog load",
    async (model) => {
      const { client } = renderSettings({ ...agent, model });
      await waitFor(() =>
        expect(client.getQueryState(["models"])?.status).toBe("success"),
      );
      expectReasoningOmitted(await saveRequest());
    },
  );

  it("preserves opening selections after a concurrent agent refresh", async () => {
    const { rerender } = renderSettings();
    await screen.findByText("Thinking mode");
    rerender(
      <AgentSettingsDialog
        agent={{ ...agent, thinking_enabled: true, reasoning_effort: "low" }}
        open
        onOpenChange={rs.fn()}
      />,
    );
    expectReasoningOmitted(await saveRequest());
  });

  it("clears incompatible reasoning after deliberately switching to a known unsupported model", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption("Default model", "Plain model");
    expect(await saveRequest()).toMatchObject({
      model: "plain",
      thinking_enabled: null,
      reasoning_effort: null,
    });
  });

  it("retains valid reasoning after deliberately switching to another supported model", async () => {
    loadModels.mockResolvedValue({
      ...catalog,
      models: [
        ...catalog.models,
        {
          ...reasoningModel,
          name: "other-reasoner",
          display_name: "Other reasoner",
        },
      ],
    });
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption("Default model", "Other reasoner");
    expect(await saveRequest()).toMatchObject({
      model: "other-reasoner",
      thinking_enabled: false,
      reasoning_effort: "high",
    });
  });

  it("submits an explicit thinking edit without rewriting effort", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption("Thinking mode", "On");
    const request = await saveRequest();
    expect(request.thinking_enabled).toBe(true);
    expect(request).not.toHaveProperty("reasoning_effort");
  });

  it.each(["pending", "failed"] as const)(
    "preserves an explicit thinking edit if the catalog becomes %s before saving",
    async (state) => {
      const { client } = renderSettings();
      await screen.findByText("Thinking mode");
      await selectOption("Thinking mode", "On");

      // The control is hidden without model data. Edit while available, then
      // clear the query so the draft survives a pending or failed reload.
      if (state === "pending") {
        loadModels.mockReturnValue(new Promise(() => undefined));
      } else {
        loadModels.mockRejectedValue(new Error("Model catalog unavailable"));
      }
      act(() => {
        void client.resetQueries({ queryKey: ["models"] });
      });
      await waitFor(() => {
        expect(client.getQueryState(["models"])?.status).toBe(
          state === "pending" ? "pending" : "error",
        );
        expect(screen.queryByText("Thinking mode")).toBeNull();
      });

      const request = await saveRequest();
      expect(request.thinking_enabled).toBe(true);
      expect(request).not.toHaveProperty("model");
      expect(request).not.toHaveProperty("reasoning_effort");
    },
  );

  it("submits an explicit inherit effort without rewriting thinking", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption("Reasoning effort", "Inherit");
    const request = await saveRequest();
    expect(request.reasoning_effort).toBe(null);
    expect(request).not.toHaveProperty("thinking_enabled");
  });

  it("omits model-dependent fields when a model switch is reverted", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption("Default model", "Plain model");
    await selectOption("Default model", "Reasoner");
    const request = await saveRequest();
    expect(request).not.toHaveProperty("model");
    expectReasoningOmitted(request);
  });

  it("omits thinking and effort edits that were restored before saving", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption("Thinking mode", "On");
    await selectOption("Thinking mode", "Off");
    await selectOption("Reasoning effort", "low");
    await selectOption("Reasoning effort", "high");
    expectReasoningOmitted(await saveRequest());
  });

  it("shows a stale required-thinking off value and lets Inherit explicitly clear it", async () => {
    loadModels.mockResolvedValue({
      ...catalog,
      models: [
        {
          ...reasoningModel,
          reasoning: {
            thinking: "required",
            effort: { values: ["low"], default: "low", aliases: {} },
            history: null,
            source: "contract",
          },
        },
      ],
    });
    renderSettings();
    await screen.findByText("Thinking mode");
    expect(
      screen.getByRole("combobox", { name: "Thinking mode" }).textContent,
    ).toContain("Off");
    expect(
      screen.getByText(enUS.agents.settingsThinkingRequiredHint),
    ).toBeTruthy();
    expectReasoningOmitted(await saveRequest());
    mutateAsync.mockClear();
    await selectOption("Thinking mode", "Inherit");
    const request = await saveRequest();
    expect(request.thinking_enabled).toBe(null);
    expect(request).not.toHaveProperty("reasoning_effort");
  });

  it.each(["limited", "unsupported"] as const)(
    "shows a saved effort outside a %s model's options and allows clearing it",
    async (state) => {
      loadModels.mockResolvedValue({
        ...catalog,
        models: [
          {
            ...reasoningModel,
            reasoning: {
              thinking: state === "limited" ? "optional" : "unsupported",
              effort:
                state === "limited"
                  ? { values: ["low"], default: "low", aliases: {} }
                  : null,
              history: null,
              source: "contract",
            },
          },
        ],
      });
      renderSettings();
      const effort = await screen.findByRole("combobox", {
        name: "Reasoning effort",
      });
      expect(effort.textContent).toContain("high");
      expect(effort.textContent).toContain("not supported");
      expectReasoningOmitted(await saveRequest());
      mutateAsync.mockClear();
      await selectOption("Reasoning effort", "Inherit");
      const request = await saveRequest();
      expect(request.reasoning_effort).toBe(null);
      expect(request).not.toHaveProperty("thinking_enabled");
    },
  );

  it("normalizes thinking and effort when deliberately switching to a required-thinking model", async () => {
    loadModels.mockResolvedValue({
      ...catalog,
      models: [
        ...catalog.models,
        {
          ...reasoningModel,
          name: "required",
          display_name: "Required model",
          reasoning: {
            thinking: "required",
            effort: { values: ["low"], default: "low", aliases: {} },
            history: null,
            source: "contract",
          },
        },
      ],
    });
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption("Default model", "Required model");
    expect(await saveRequest()).toMatchObject({
      model: "required",
      thinking_enabled: null,
      reasoning_effort: null,
    });
  });
});
