import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

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
rs.mock("@/core/models/hooks", () => ({ useModels: () => ({ models: [] }) }));
rs.mock("@/core/subagents", () => ({
  useSubagents: () => ({ subagents: [] }),
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
