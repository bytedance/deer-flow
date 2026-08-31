import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ToolSettingsPage } from "@/components/workspace/settings/tool-settings-page";

const mcpMockState = rs.hoisted(() => ({
  isPending: false,
  mutate: rs.fn(),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: { loading: "Loading" },
      settings: {
        tools: {
          title: "Tools",
          description: "Manage MCP tools",
          adminRequired: "Admin required",
          empty: "No tools",
        },
      },
    },
  }),
}));

rs.mock("@/core/mcp/hooks", () => ({
  useMCPConfig: () => ({
    config: {
      mcp_servers: {
        github: { enabled: true, description: "GitHub tools" },
        remote: { enabled: false, description: "Remote tools" },
      },
    },
    isLoading: false,
    error: null,
  }),
  useEnableMCPServer: () => ({
    isPending: mcpMockState.isPending,
    mutate: mcpMockState.mutate,
  }),
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

afterEach(() => {
  mcpMockState.isPending = false;
  mcpMockState.mutate.mockReset();
  cleanup();
});

describe("ToolSettingsPage MCP switches", () => {
  it("disables every switch while a targeted update is pending", () => {
    mcpMockState.isPending = true;

    render(<ToolSettingsPage />);

    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(2);
    for (const item of switches) {
      expect((item as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("submits only the selected server state when idle", () => {
    render(<ToolSettingsPage />);

    const switches = screen.getAllByRole("switch");
    const githubSwitch = switches[0];
    expect(githubSwitch).toBeDefined();
    expect((githubSwitch as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(githubSwitch!);

    expect(mcpMockState.mutate).toHaveBeenCalledWith({
      serverName: "github",
      enabled: false,
    });
  });
});
