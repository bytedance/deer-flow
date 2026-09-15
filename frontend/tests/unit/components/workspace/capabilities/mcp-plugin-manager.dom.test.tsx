import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { MCPPluginManager } from "@/components/workspace/capabilities/mcp-plugin-manager";

const mcpMockState = rs.hoisted(() => ({
  isPending: false,
  isLoading: false,
  error: null as Error | null,
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
      capabilities: {
        enabled: "Enabled",
        disabled: "Disabled",
        details: "View details",
        addPlugin: "Add server",
        mcpLabel: "MCP",
        mcpDescription: "MCP tools",
      },
      common: {
        error: "Error:",
        loading: "Loading",
        cancel: "Cancel",
        save: "Save",
        delete: "Delete",
        edit: "Edit",
      },
      settings: {
        tools: {
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
    isLoading: mcpMockState.isLoading,
    error: mcpMockState.error,
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
  mcpMockState.isLoading = false;
  mcpMockState.error = null;
  mcpMockState.updateIsPending = false;
  mcpMockState.mutate.mockReset();
  mcpMockState.updateMutate.mockReset();
  mcpMockState.servers = {};
  cleanup();
});

describe("MCPPluginManager MCP switches", () => {
  it.each(["loading", "error"])(
    "preserves plugin filters and other plugins during an MCP %s",
    (state) => {
      mcpMockState.isLoading = state === "loading";
      mcpMockState.error =
        state === "error" ? new Error("request failed") : null;
      render(
        <MCPPluginManager toolbar={<button>All plugins</button>}>
          <button>Configure Lark</button>
        </MCPPluginManager>,
      );
      expect(
        screen.getByRole("button", { name: "Configure Lark" }),
      ).toBeDefined();
      expect(screen.getByRole("button", { name: "All plugins" })).toBeDefined();
      expect(screen.queryByRole("button", { name: "Add server" })).toBeNull();
    },
  );

  it("renders a localized load error", () => {
    mcpMockState.error = new Error("request failed");

    render(<MCPPluginManager />);

    expect(screen.getByText("Error: request failed")).toBeDefined();
  });

  it("disables every switch while a targeted update is pending", () => {
    twoServers();
    mcpMockState.isPending = true;

    render(<MCPPluginManager />);

    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(2);
    for (const item of switches) {
      expect((item as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("submits only the selected server state when idle", () => {
    twoServers();

    render(<MCPPluginManager />);

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

describe("MCPPluginManager add server", () => {
  it("submits only the pasted servers to the atomic create endpoint", () => {
    twoServers();

    render(<MCPPluginManager />);
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

    render(<MCPPluginManager />);
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

    render(<MCPPluginManager />);
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

    render(<MCPPluginManager />);

    expect(screen.getByText("No tools")).toBeDefined();
    expect(
      screen
        .getByRole("button", { name: "Add server" })
        .hasAttribute("disabled"),
    ).toBe(false);
  });

  it("rejects an existing name instead of silently replacing it", () => {
    twoServers();

    render(<MCPPluginManager />);
    openAddDialog();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '{"github": {"command": "uvx"}}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mcpMockState.updateMutate).not.toHaveBeenCalled();
    expect(screen.getByText('Server "github" already exists')).toBeDefined();
  });
});

describe("MCPPluginManager edit server", () => {
  it("prefills the complete server definition", () => {
    twoServers();

    render(<MCPPluginManager />);
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

    render(<MCPPluginManager />);
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

    render(<MCPPluginManager />);
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

    render(<MCPPluginManager />);
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

describe("MCPPluginManager remove server", () => {
  it("submits only the selected server name", () => {
    twoServers();

    render(<MCPPluginManager />);
    fireEvent.click(screen.getByRole("button", { name: "Delete github" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(lastMutation()).toEqual({
      operation: "delete",
      serverName: "github",
    });
  });

  it("does not write when the confirmation is dismissed", () => {
    twoServers();

    render(<MCPPluginManager />);
    fireEvent.click(screen.getByRole("button", { name: "Delete github" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mcpMockState.updateMutate).not.toHaveBeenCalled();
  });

  it("deletes a configured server whose name is empty", () => {
    setServers({ "": { enabled: false, description: "Legacy server" } });

    render(<MCPPluginManager />);
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
