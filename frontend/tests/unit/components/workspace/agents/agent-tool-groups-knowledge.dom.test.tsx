import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { AgentSettingsDialog } from "@/components/workspace/agents/agent-settings-dialog";
import type { Agent } from "@/core/agents";
import { enUS } from "@/core/i18n/locales/en-US";
import type { KnowledgeScopeSnapshot } from "@/core/knowledge";

const { mutateAsync } = rs.hoisted(() => ({
  mutateAsync: rs.fn().mockResolvedValue({}),
}));
rs.mock("@/core/agents", () => ({
  useAgentToolGroups: () => ({
    toolGroups: ["web", "knowledge", "file:read"],
    isLoading: false,
    error: null,
  }),
  useUpdateAgent: () => ({ mutateAsync, isPending: false }),
}));
rs.mock("@/core/features", () => ({
  useKnowledgeBaseEnabled: () => ({ scopeSelectionEnabled: true }),
}));
rs.mock("@/core/models/hooks", () => ({ useModels: () => ({ models: [] }) }));
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

const selectedScope: KnowledgeScopeSnapshot = {
  version: 1,
  mode: "selected",
  dataset_ids: ["policies"],
};
const agent: Agent = {
  name: "researcher",
  description: "",
  model: null,
  tool_groups: ["web", "knowledge"],
  skills: null,
  knowledge_scope: selectedScope,
};

afterEach(() => {
  cleanup();
  mutateAsync.mockClear();
  rs.restoreAllMocks();
});

function renderSettings(value: Agent) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }
  return render(
    <AgentSettingsDialog agent={value} open onOpenChange={rs.fn()} />,
    { wrapper: Wrapper },
  );
}

async function saveRequest() {
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
  return (
    mutateAsync.mock.calls[0]![0] as {
      request: Record<string, unknown>;
    }
  ).request;
}

describe("tool access and default knowledge", () => {
  it.each([
    ["selected", ["web"], selectedScope],
    ["selected", [], selectedScope],
    ["disabled", ["web"], { version: 1, mode: "disabled" }],
    ["disabled", [], { version: 1, mode: "disabled" }],
  ] as const)(
    "clears a %s knowledge default atomically when groups become %j",
    async (_mode, groups, scope) => {
      renderSettings({ ...agent, knowledge_scope: scope });
      fireEvent.click(screen.getByLabelText("knowledge"));
      if (groups.length === 0) fireEvent.click(screen.getByLabelText("web"));

      expect(await saveRequest()).toMatchObject({
        tool_groups: groups,
        knowledge_scope: null,
      });
    },
  );

  it("clears the default when inherited tool access is disabled", async () => {
    renderSettings({ ...agent, tool_groups: null });
    fireEvent.click(screen.getByLabelText("Use every configured tool group"));

    expect(await saveRequest()).toMatchObject({
      tool_groups: [],
      knowledge_scope: null,
    });
  });

  it("omits knowledge and groups when a draft restriction is restored", async () => {
    renderSettings(agent);
    fireEvent.click(screen.getByLabelText("knowledge"));
    fireEvent.click(screen.getByLabelText("knowledge"));

    const request = await saveRequest();
    expect(request).not.toHaveProperty("tool_groups");
    expect(request).not.toHaveProperty("knowledge_scope");
  });

  it("preserves concurrent defaults on a rename-only save", async () => {
    const { rerender } = renderSettings(agent);
    rerender(
      <AgentSettingsDialog
        agent={{
          ...agent,
          tool_groups: ["web"],
          knowledge_scope: { version: 1, mode: "disabled" },
        }}
        open
        onOpenChange={rs.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Renamed" },
    });

    const request = await saveRequest();
    expect(request).not.toHaveProperty("tool_groups");
    expect(request).not.toHaveProperty("knowledge_scope");
  });

  it("preserves an untouched default when other groups change", async () => {
    renderSettings(agent);
    fireEvent.click(screen.getByLabelText("web"));

    const request = await saveRequest();
    expect(request.tool_groups).toEqual(["knowledge"]);
    expect(request).not.toHaveProperty("knowledge_scope");
  });

  it.each(["knowledge", "Use every configured tool group"])(
    "requires saved access before choosing knowledge after enabling %s",
    async (label) => {
      const fetch = rs
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(
          Response.json({ items: [], page: 1, page_size: 100, total: 0 }),
        );
      renderSettings({ ...agent, tool_groups: ["web"], knowledge_scope: null });
      fireEvent.click(screen.getByLabelText(label));

      const trigger = screen.getByTestId("knowledge-scope-trigger");
      expect((trigger as HTMLButtonElement).disabled).toBe(true);
      expect(
        screen.getByText(enUS.agents.settingsKnowledgeSaveToolAccess),
      ).toBeTruthy();
      fireEvent.click(trigger);
      expect(fetch).not.toHaveBeenCalled();
      expect((await saveRequest()).tool_groups).toEqual(
        label === "knowledge" ? ["web", "knowledge"] : null,
      );
    },
  );

  it("loads the catalog after knowledge access is persisted", async () => {
    const fetch = rs.spyOn(globalThis, "fetch").mockImplementation((input) =>
      Promise.resolve(
        Response.json(
          (typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url
          ).includes("/capabilities?")
            ? {
                operations: [
                  "search",
                  "catalog",
                  "documents",
                  "dataset_filter",
                  "document_filter",
                ],
                scope_selection_enabled: true,
              }
            : {
                items: [{ id: "policies", name: "Policies", selectable: true }],
                page: 1,
                page_size: 100,
                total: 1,
              },
        ),
      ),
    );
    const { rerender } = renderSettings({
      ...agent,
      tool_groups: ["web"],
      knowledge_scope: null,
    });
    fireEvent.click(screen.getByLabelText("knowledge"));
    rerender(
      <AgentSettingsDialog
        agent={{ ...agent, knowledge_scope: null }}
        open
        onOpenChange={rs.fn()}
      />,
    );

    const trigger = screen.getByTestId("knowledge-scope-trigger");
    expect((trigger as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(trigger);
    await waitFor(() =>
      expect(
        screen.getByRole<HTMLInputElement>("radio", {
          name: "Selected knowledge bases",
        }).disabled,
      ).toBe(false),
    );
    fireEvent.click(
      screen.getByRole("radio", { name: "Selected knowledge bases" }),
    );
    await screen.findByText("Policies");
    expect(fetch).toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Policies"));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect((await saveRequest()).knowledge_scope).toMatchObject({
      mode: "selected",
      dataset_ids: ["policies"],
    });
  });
});
