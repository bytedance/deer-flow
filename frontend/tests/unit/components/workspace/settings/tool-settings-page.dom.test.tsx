import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ToolSettingsPage } from "@/components/workspace/settings/tool-settings-page";

const mcpMockState = rs.hoisted(() => ({
  isPending: false,
  mutate: rs.fn(),
  updateIsPending: false,
  updateMutate: rs.fn(),
  servers: {} as Record<string, unknown>,
}));

// A server carrying config this page never renders: it must survive a write
// that only meant to add or remove some other entry.
const DURABLE_TASK_SERVER = {
  enabled: true,
  description: "Remote tools",
  type: "http",
  url: "https://example.test/mcp",
  task_toolsets: [{ submit: "run", status: "poll" }],
  routing: { mode: "prefer", priority: 50 },
  headers: { "X-API-Key": "***" },
};

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "Loading",
        cancel: "Cancel",
        save: "Save",
        delete: "Delete",
        edit: "Edit",
      },
      settings: {
        tools: {
          title: "Tools",
          description: "Manage MCP tools",
          adminRequired: "Admin required",
          empty: "No tools",
          addServer: "Add server",
          addServerDescription: "Paste the definition",
          addServerPlaceholder: "{}",
          serverDefinitionLabel: "MCP server JSON definition",
          definitionEmpty: "Paste a definition",
          definitionInvalidJson: "Enter valid JSON",
          definitionRootNotObject: "Enter a JSON object",
          definitionNoServers: "No server found",
          definitionServerNotObject:
            'The configuration for server "{name}" must be an object',
          editServer: "Edit MCP server",
          editServerDescription: 'Edit "{name}"',
          editSingleServer: "Edit exactly one server",
          editServerNameMismatch: 'Keep the name "{name}"',
          serverAlreadyExists: 'Server "{name}" already exists',
          removeServer: "Remove MCP server",
          removeServerDescription: 'Remove "{name}"?',
          unnamedServer: "(empty name)",
        },
      },
    },
  }),
}));

rs.mock("@/core/mcp/hooks", () => ({
  useMCPConfig: () => ({
    config: { mcp_servers: mcpMockState.servers },
    isLoading: false,
    error: null,
  }),
  useEnableMCPServer: () => ({
    isPending: mcpMockState.isPending,
    mutate: mcpMockState.mutate,
  }),
  useMCPServerMutation: () => ({
    isPending: mcpMockState.updateIsPending,
    mutate: mcpMockState.updateMutate,
  }),
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

function setServers(servers: Record<string, unknown>) {
  mcpMockState.servers = servers;
}

function twoServers() {
  setServers({
    github: { enabled: true, description: "GitHub tools" },
    remote: { ...DURABLE_TASK_SERVER, enabled: false },
  });
}

/** The targeted mutation variables handed to the last call. */
function lastMutation() {
  const call = mcpMockState.updateMutate.mock.calls.at(-1);
  return call?.[0] as Record<string, unknown>;
}

function openAddDialog() {
  fireEvent.click(screen.getByRole("button", { name: "Add server" }));
}

function openEditDialog(name: string) {
  fireEvent.click(screen.getByRole("button", { name: `Edit ${name}` }));
}

function definitionTextbox(): HTMLTextAreaElement {
  const element = screen.getByRole("textbox");
  if (!(element instanceof HTMLTextAreaElement)) {
    throw new TypeError("MCP definition editor must be a textarea");
  }
  return element;
}

afterEach(() => {
  mcpMockState.isPending = false;
  mcpMockState.updateIsPending = false;
  mcpMockState.mutate.mockReset();
  mcpMockState.updateMutate.mockReset();
  mcpMockState.servers = {};
  cleanup();
});

describe("ToolSettingsPage MCP switches", () => {
  it("disables every switch while a targeted update is pending", () => {
    twoServers();
    mcpMockState.isPending = true;

    render(<ToolSettingsPage />);

    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(2);
    for (const item of switches) {
      expect((item as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("submits only the selected server state when idle", () => {
    twoServers();

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

describe("ToolSettingsPage add server", () => {
  it("submits only the pasted servers to the atomic create endpoint", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openAddDialog();
    fireEvent.change(screen.getByRole("textbox"), {
      target: {
        value: '{"mcpServers": {"added": {"command": "npx", "args": []}}}',
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(lastMutation()).toEqual({
      operation: "create",
      servers: {
        added: { command: "npx", args: [], enabled: true, description: "" },
      },
    });
  });

  it("does not submit stale sibling configurations while adding", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openAddDialog();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '{"added": {"command": "uvx"}}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(lastMutation()).toEqual({
      operation: "create",
      servers: {
        added: { command: "uvx", enabled: true, description: "" },
      },
    });
  });

  it("reports a malformed definition without writing", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openAddDialog();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "{not json" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mcpMockState.updateMutate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe("Enter valid JSON");
    expect(
      screen.getByRole("textbox", { name: "MCP server JSON definition" }),
    ).toBeDefined();
  });

  it("offers the add action when no server is configured yet", () => {
    setServers({});

    render(<ToolSettingsPage />);

    expect(screen.getByText("No tools")).toBeDefined();
    expect(
      screen
        .getByRole("button", { name: "Add server" })
        .hasAttribute("disabled"),
    ).toBe(false);
  });

  it("rejects an existing name instead of silently replacing it", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openAddDialog();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '{"github": {"command": "uvx"}}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mcpMockState.updateMutate).not.toHaveBeenCalled();
    expect(screen.getByText('Server "github" already exists')).toBeDefined();
  });
});

describe("ToolSettingsPage edit server", () => {
  it("prefills the complete server definition", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openEditDialog("remote");

    const definition = JSON.parse(definitionTextbox().value) as {
      mcpServers: Record<string, unknown>;
    };
    expect(Object.keys(definition.mcpServers)).toEqual(["remote"]);
    expect(definition.mcpServers.remote).toEqual({
      ...DURABLE_TASK_SERVER,
      enabled: false,
    });
  });

  it("updates only one server while preserving all of its hidden fields", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openEditDialog("remote");
    const textbox = definitionTextbox();
    const definition = JSON.parse(textbox.value) as {
      mcpServers: Record<string, Record<string, unknown>>;
    };
    definition.mcpServers.remote!.description = "Updated remote tools";
    fireEvent.change(textbox, {
      target: { value: JSON.stringify(definition) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(lastMutation()).toEqual({
      operation: "update",
      serverName: "remote",
      server: {
        ...DURABLE_TASK_SERVER,
        enabled: false,
        description: "Updated remote tools",
      },
    });
  });

  it("rejects renaming through the edit dialog", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openEditDialog("github");
    fireEvent.change(screen.getByRole("textbox"), {
      target: {
        value: '{"mcpServers": {"renamed": {"command": "npx"}}}',
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mcpMockState.updateMutate).not.toHaveBeenCalled();
    expect(screen.getByText('Keep the name "github"')).toBeDefined();
  });

  it("rejects editing multiple servers at once", () => {
    twoServers();

    render(<ToolSettingsPage />);
    openEditDialog("github");
    fireEvent.change(screen.getByRole("textbox"), {
      target: {
        value:
          '{"mcpServers": {"github": {"command": "npx"}, "extra": {"command": "uvx"}}}',
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mcpMockState.updateMutate).not.toHaveBeenCalled();
    expect(screen.getByText("Edit exactly one server")).toBeDefined();
  });
});

describe("ToolSettingsPage remove server", () => {
  it("submits only the selected server name", () => {
    twoServers();

    render(<ToolSettingsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Delete github" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(lastMutation()).toEqual({
      operation: "delete",
      serverName: "github",
    });
  });

  it("does not write when the confirmation is dismissed", () => {
    twoServers();

    render(<ToolSettingsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Delete github" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mcpMockState.updateMutate).not.toHaveBeenCalled();
  });

  it("deletes a configured server whose name is empty", () => {
    setServers({ "": { enabled: false, description: "Legacy server" } });

    render(<ToolSettingsPage />);
    fireEvent.click(
      screen.getByRole("button", { name: "Delete (empty name)" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(lastMutation()).toEqual({
      operation: "delete",
      serverName: "",
    });
  });
});
