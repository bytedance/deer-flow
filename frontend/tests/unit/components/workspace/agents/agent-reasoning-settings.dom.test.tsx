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

async function selectOption(index: number, name: string) {
  fireEvent.keyDown(screen.getAllByRole("combobox")[index]!, {
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
    const client = new QueryClient();
    client.setQueryDefaults(["models"], { retryDelay: 0 });
    clients.push(client);
    render(
      <QueryClientProvider client={client}>
        <AgentSettingsDialog agent={agent} open onOpenChange={rs.fn()} />
      </QueryClientProvider>,
    );
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

  it("does not infer unsupported reasoning when switching to an unresolved global default", async () => {
    loadModels.mockReturnValue(new Promise(() => undefined));
    renderSettings();
    await selectOption(0, "Use global default");
    const request = await saveRequest();
    expect(request.model).toBe(null);
    expectReasoningOmitted(request);
  });

  it("normalizes a global-default switch when the pending catalog resolves before saving", async () => {
    let resolveCatalog!: (value: ModelsResponse) => void;
    loadModels.mockReturnValue(
      new Promise((resolve) => {
        resolveCatalog = resolve;
      }),
    );
    const { client } = renderSettings();
    await selectOption(0, "Use global default");
    expect(client.getQueryState(["models"])?.status).toBe("pending");

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
    await selectOption(0, "Plain model");
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
    await selectOption(0, "Other reasoner");
    expect(await saveRequest()).toMatchObject({
      model: "other-reasoner",
      thinking_enabled: false,
      reasoning_effort: "high",
    });
  });

  it("submits an explicit thinking edit without rewriting effort", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption(1, "On");
    const request = await saveRequest();
    expect(request.thinking_enabled).toBe(true);
    expect(request).not.toHaveProperty("reasoning_effort");
  });

  it.each(["pending", "failed"] as const)(
    "preserves an explicit thinking edit if the catalog becomes %s before saving",
    async (state) => {
      const { client } = renderSettings();
      await screen.findByText("Thinking mode");
      await selectOption(1, "On");

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
    await selectOption(2, "Inherit");
    const request = await saveRequest();
    expect(request.reasoning_effort).toBe(null);
    expect(request).not.toHaveProperty("thinking_enabled");
  });

  it("omits model-dependent fields when a model switch is reverted", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption(0, "Plain model");
    await selectOption(0, "Reasoner");
    const request = await saveRequest();
    expect(request).not.toHaveProperty("model");
    expectReasoningOmitted(request);
  });

  it("omits thinking and effort edits that were restored before saving", async () => {
    renderSettings();
    await screen.findByText("Thinking mode");
    await selectOption(1, "On");
    await selectOption(1, "Off");
    await selectOption(2, "low");
    await selectOption(2, "high");
    expectReasoningOmitted(await saveRequest());
  });

  it("does not normalize an untouched off value when the catalog requires thinking", async () => {
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
    expectReasoningOmitted(await saveRequest());
  });

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
    await selectOption(0, "Required model");
    expect(await saveRequest()).toMatchObject({
      model: "required",
      thinking_enabled: null,
      reasoning_effort: null,
    });
  });
});
