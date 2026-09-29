import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { toast } from "sonner";

import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { AgentSettingsDialog } from "@/components/workspace/agents/agent-settings-dialog";
import type { Agent } from "@/core/agents";
import { enUS } from "@/core/i18n/locales/en-US";

const { mutateAsync } = rs.hoisted(() => ({
  mutateAsync: rs.fn().mockResolvedValue({}),
}));
rs.mock("@/core/agents", () => ({
  useUpdateAgent: () => ({ mutateAsync, isPending: false }),
}));
rs.mock("@/core/features", () => ({
  useKnowledgeBaseEnabled: () => ({ scopeSelectionEnabled: false }),
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

const agent: Agent = {
  name: "reviewer",
  display_name: "代码审查助手",
  description: "",
  model: null,
  tool_groups: null,
  skills: null,
};
afterEach(() => {
  cleanup();
  mutateAsync.mockClear();
});

describe("custom agent display names", () => {
  it("accepts 100 astral code points without an HTML code-unit limit", async () => {
    render(<AgentSettingsDialog agent={agent} open onOpenChange={rs.fn()} />);
    const input = screen.getByLabelText("Display name");
    expect(input.hasAttribute("maxlength")).toBe(false);
    fireEvent.change(input, { target: { value: "🦌".repeat(100) } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          request: expect.objectContaining({ display_name: "🦌".repeat(100) }),
        }),
      ),
    );
  });

  it("rejects 101 code points before saving", () => {
    render(<AgentSettingsDialog agent={agent} open onOpenChange={rs.fn()} />);
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "🦌".repeat(101) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("shows Unicode names and falls back for legacy or cleared names", () => {
    const { rerender } = render(
      <AgentWelcome agent={agent} agentName="reviewer" />,
    );
    expect(screen.getByText("代码审查助手")).toBeTruthy();
    for (const display_name of [undefined, null, ""]) {
      rerender(
        <AgentWelcome
          agent={{ ...agent, display_name }}
          agentName="reviewer"
        />,
      );
      expect(screen.getByText("reviewer")).toBeTruthy();
    }
  });

  it("saves a display name using the stable identifier", async () => {
    render(<AgentSettingsDialog agent={agent} open onOpenChange={rs.fn()} />);
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "审查员 🦌" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "reviewer",
          request: expect.objectContaining({ display_name: "审查员 🦌" }),
        }),
      ),
    );
  });

  it("clears a blank name without renaming the agent", async () => {
    render(<AgentSettingsDialog agent={agent} open onOpenChange={rs.fn()} />);
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "reviewer",
          request: expect.objectContaining({ display_name: null }),
        }),
      ),
    );
  });
});

describe("capability selection update isolation", () => {
  it("omits untouched selections after a concurrent agent refresh", async () => {
    const opened = {
      ...agent,
      mcp_plugins: ["old-plugin"],
      skills: ["old-skill"],
    };
    const { rerender } = render(
      <AgentSettingsDialog agent={opened} open onOpenChange={rs.fn()} />,
    );
    rerender(
      <AgentSettingsDialog
        agent={{
          ...opened,
          mcp_plugins: ["new-plugin"],
          skills: ["new-skill"],
        }}
        open
        onOpenChange={rs.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Rename only" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const { request } = mutateAsync.mock.calls[0]![0] as {
      request: Record<string, unknown>;
    };
    expect(request).not.toHaveProperty("mcp_plugins");
    expect(request).not.toHaveProperty("skills");
    expect(request.display_name).toBe("Rename only");
  });

  it.each([
    ["mcp_plugins", 0, null, []],
    ["skills", 1, null, []],
    ["mcp_plugins", 0, [], null],
    ["skills", 1, [], null],
  ] as const)(
    "saves an intentional %s change at index %s from %s to %s only",
    async (field, index, initial, selected) => {
      render(
        <AgentSettingsDialog
          agent={{ ...agent, [field]: initial }}
          open
          onOpenChange={rs.fn()}
        />,
      );
      fireEvent.click(screen.getAllByLabelText("Use all enabled")[index]!);
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
      const { request } = mutateAsync.mock.calls[0]![0] as {
        request: Record<string, unknown>;
      };
      expect(request[field]).toEqual(selected);
      expect(request).not.toHaveProperty(
        field === "skills" ? "mcp_plugins" : "skills",
      );
    },
  );

  it("omits a selection that was changed and restored", async () => {
    render(<AgentSettingsDialog agent={agent} open onOpenChange={rs.fn()} />);
    const all = screen.getAllByLabelText("Use all enabled")[0]!;
    fireEvent.click(all);
    fireEvent.click(all);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const { request } = mutateAsync.mock.calls[0]![0] as {
      request: Record<string, unknown>;
    };
    expect(request).not.toHaveProperty("mcp_plugins");
    expect(request).not.toHaveProperty("skills");
  });
});
