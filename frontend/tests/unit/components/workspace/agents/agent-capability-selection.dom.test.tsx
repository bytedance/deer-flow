import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { AgentCapabilitySelection } from "@/components/workspace/agents/agent-capability-selection";
import { enUS } from "@/core/i18n/locales/en-US";

const { useAgentToolGroups } = rs.hoisted(() => ({
  useAgentToolGroups: rs.fn(),
}));
rs.mock("@/core/agents", () => ({ useAgentToolGroups }));
rs.mock("@/core/capabilities/hooks", () => ({
  useCapabilityInstallations: () => ({
    data: { items: [] },
    isLoading: false,
    isError: false,
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

afterEach(() => {
  cleanup();
  useAgentToolGroups.mockReset();
});

function selection(onToolGroupsChange = rs.fn()) {
  return (
    <AgentCapabilitySelection
      plugins={null}
      skills={null}
      toolGroups={["web", "legacy-tools"]}
      onPluginsChange={rs.fn()}
      onSkillsChange={rs.fn()}
      onToolGroupsChange={onToolGroupsChange}
    />
  );
}

describe("tool-group catalog availability", () => {
  it.each([
    { state: "loading", isLoading: true, error: null },
    { state: "failed", isLoading: false, error: new Error("Load failed") },
  ])("keeps saved groups neutral and removable when $state", (query) => {
    useAgentToolGroups.mockReturnValue({ toolGroups: [], ...query });
    const onChange = rs.fn();
    render(selection(onChange));

    for (const name of ["web", "legacy-tools"]) {
      const checkbox = screen.getByLabelText<HTMLInputElement>(name);
      expect(checkbox.checked).toBe(true);
      expect(checkbox.disabled).toBe(false);
    }
    expect(screen.queryByText(/\(unavailable\)/)).toBeNull();
    if (query.isLoading) {
      expect(screen.getByText(enUS.common.loading)).toBeTruthy();
    } else {
      expect(screen.getByRole("alert").textContent).toBe(
        enUS.agents.settingsToolGroupsLoadFailed,
      );
    }

    fireEvent.click(screen.getByLabelText("legacy-tools"));
    expect(onChange).toHaveBeenCalledWith(["web"]);
  });

  it("marks only missing groups unavailable after a successful load", () => {
    useAgentToolGroups.mockReturnValue({
      toolGroups: ["web"],
      isLoading: false,
      error: null,
    });
    const onChange = rs.fn();
    render(selection(onChange));

    expect(screen.getByLabelText<HTMLInputElement>("web").checked).toBe(true);
    const missing = screen.getByLabelText<HTMLInputElement>(
      "legacy-tools (unavailable)",
    );
    expect(missing.checked).toBe(true);
    fireEvent.click(missing);
    expect(onChange).toHaveBeenCalledWith(["web"]);
  });

  it("updates availability after loading without changing the selection", () => {
    useAgentToolGroups.mockReturnValue({
      toolGroups: [],
      isLoading: true,
      error: null,
    });
    const onChange = rs.fn();
    const { rerender } = render(selection(onChange));
    expect(screen.getByLabelText("legacy-tools")).toBeTruthy();

    useAgentToolGroups.mockReturnValue({
      toolGroups: ["web"],
      isLoading: false,
      error: null,
    });
    rerender(selection(onChange));

    expect(screen.getByLabelText<HTMLInputElement>("web").checked).toBe(true);
    expect(
      screen.getByLabelText<HTMLInputElement>("legacy-tools (unavailable)")
        .checked,
    ).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });
});
