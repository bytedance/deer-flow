import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { AgentTracingSettings } from "@/components/workspace/agents/agent-tracing-settings";
import { GatewayApiError } from "@/core/api/errors";
import { AuthQueryScopeContext } from "@/core/auth/query-scope";
import { enUS } from "@/core/i18n/locales/en-US";
import * as api from "@/core/tracing/api";
import type {
  AgentTracing,
  TracingProfilesResponse,
} from "@/core/tracing/types";

rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/tracing/api", () => ({
  loadTracingProfiles: rs.fn(),
  loadAgentTracing: rs.fn(),
  saveAgentTracing: rs.fn(),
  saveTracingProfile: rs.fn(),
}));

const binding: AgentTracing = {
  mode: "inherit",
  profile_id: null,
  revision: 2,
  effective_revision: "global:5",
  source: "global",
  destinations: [
    {
      provider: "arize",
      endpoint: "https://otlp.arize.com",
      project: "global-project",
      space_id: "space",
    },
  ],
  status: "pending",
  error: null,
  delivery_verified: false,
  can_select: true,
};
const profiles: TracingProfilesResponse = {
  profiles: [
    {
      id: "qa",
      name: "QA profile",
      revision: 3,
      providers: [
        {
          provider: "arize",
          endpoint: "https://otlp.arize.com",
          project: "qa",
          space_id: "space",
          transport: "http",
          has_api_key: true,
          has_secret_key: false,
        },
      ],
      allowed_user_ids: ["alice"],
    },
  ],
  can_manage: false,
  available: true,
  reason: null,
};
const clients: QueryClient[] = [];
beforeEach(() => {
  rs.mocked(api.loadTracingProfiles).mockResolvedValue(profiles);
  rs.mocked(api.loadAgentTracing).mockResolvedValue(binding);
  rs.mocked(api.saveAgentTracing).mockResolvedValue({
    ...binding,
    mode: "disabled",
    revision: 3,
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  rs.resetAllMocks();
});
function mount(user = "alice") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const view = render(
    <QueryClientProvider client={client}>
      <AuthQueryScopeContext.Provider value={user}>
        <AgentTracingSettings agentName="research" />
      </AuthQueryScopeContext.Provider>
    </QueryClientProvider>,
  );
  return { client, ...view };
}
async function selectMode(value: string) {
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Tracing mode" }), {
    key: "ArrowDown",
  });
  fireEvent.click(await screen.findByRole("option", { name: value }));
}

it("lets an authorized non-admin select tracing while keeping credential management hidden", async () => {
  mount();
  await screen.findByText("global-project", { exact: false });
  expect(
    screen.queryByRole("button", { name: "Add tracing profile" }),
  ).toBeNull();
  expect(screen.getByText("Delivery has not been verified.")).toBeTruthy();
  expect(screen.getByText("Pending initialization")).toBeTruthy();
  await selectMode("Disabled");
  fireEvent.click(screen.getByRole("button", { name: "Apply tracing" }));
  await waitFor(() =>
    expect(api.saveAgentTracing).toHaveBeenCalledWith("research", {
      mode: "disabled",
      profile_id: null,
      expected_revision: 2,
    }),
  );
});

it("preserves an unsaved mode after a save failure", async () => {
  rs.mocked(api.saveAgentTracing).mockRejectedValue(
    new GatewayApiError({
      status: 409,
      code: "revision_conflict",
      message: "Conflict",
      rawMessage: "Conflict",
      params: {},
    }),
  );
  mount();
  await screen.findByRole("combobox", { name: "Tracing mode" });
  await selectMode("Disabled");
  fireEvent.click(screen.getByRole("button", { name: "Apply tracing" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("alert").textContent).toContain("changed elsewhere");
  expect(
    screen.getByRole("combobox", { name: "Tracing mode" }).textContent,
  ).toContain("Disabled");
});

it("blocks configured mode while the profile catalog is unresolved", async () => {
  rs.mocked(api.loadTracingProfiles).mockReturnValue(
    new Promise(() => undefined),
  );
  mount();
  await screen.findByRole("combobox", { name: "Tracing mode" });
  await selectMode("Configured profile");
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Apply tracing" })
      .disabled,
  ).toBe(true);
  expect(api.saveAgentTracing).not.toHaveBeenCalled();
});

it("explains the deployment lock without implying an administrator lacks permission", async () => {
  rs.mocked(api.loadAgentTracing).mockResolvedValue({
    ...binding,
    can_select: false,
    error: "tracing_operator_lock",
  });
  mount();
  await screen.findByText(
    "Monocle is enabled by the deployment. Agent tracing overrides are locked.",
  );
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Apply tracing" })
      .disabled,
  ).toBe(true);
});

it("isolates fetched destinations and drafts after an account switch", async () => {
  const { client, rerender } = mount();
  await screen.findByText("global-project", { exact: false });
  rs.mocked(api.loadAgentTracing).mockReturnValue(new Promise(() => undefined));
  rs.mocked(api.loadTracingProfiles).mockReturnValue(
    new Promise(() => undefined),
  );
  rerender(
    <QueryClientProvider client={client}>
      <AuthQueryScopeContext.Provider value="bob">
        <AgentTracingSettings agentName="research" />
      </AuthQueryScopeContext.Provider>
    </QueryClientProvider>,
  );
  expect(screen.queryByText("global-project", { exact: false })).toBeNull();
  expect(
    client.getQueryData(["agent-tracing", "alice", "research"]),
  ).toBeTruthy();
  expect(
    client.getQueryData(["agent-tracing", "bob", "research"]),
  ).toBeUndefined();
});

it("shows unavailable storage rather than an active destination", async () => {
  rs.mocked(api.loadAgentTracing).mockResolvedValue({
    ...binding,
    status: "active",
  });
  rs.mocked(api.loadTracingProfiles).mockResolvedValue({
    ...profiles,
    available: false,
    reason: "durable_storage_required",
  });
  mount();
  await screen.findByText("durable_storage_required");
  expect(
    screen.queryByText("Configuration ready · delivery unverified"),
  ).toBeNull();
  expect(screen.getByText("Unavailable", { exact: true })).toBeTruthy();
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Apply tracing" })
      .disabled,
  ).toBe(true);
});

it("does not backfill saved credentials when an administrator edits a profile", async () => {
  rs.mocked(api.loadTracingProfiles).mockResolvedValue({
    ...profiles,
    can_manage: true,
  });
  rs.mocked(api.saveTracingProfile).mockResolvedValue(profiles.profiles[0]!);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit QA profile" }),
  );
  expect(screen.getByLabelText<HTMLInputElement>("Arize API key").value).toBe(
    "",
  );
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(api.saveTracingProfile).toHaveBeenCalled());
  const body = rs.mocked(api.saveTracingProfile).mock.calls[0]![1];
  expect(body.expected_revision).toBe(3);
  expect(body.providers[0]).not.toHaveProperty("api_key");
});

it("preserves and explicitly updates the LangSmith workspace without resending credentials", async () => {
  const profile = {
    ...profiles.profiles[0]!,
    name: "LangSmith shared",
    providers: [
      {
        provider: "langsmith" as const,
        endpoint: "https://api.smith.langchain.com",
        project: "qa",
        workspace_id: "workspace-a",
        has_api_key: true,
        has_secret_key: false,
      },
    ],
  };
  rs.mocked(api.loadTracingProfiles).mockResolvedValue({
    ...profiles,
    can_manage: true,
    profiles: [profile],
  });
  rs.mocked(api.saveTracingProfile).mockRejectedValue(new Error("Offline"));
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit LangSmith shared" }),
  );
  expect(
    screen.getByLabelText<HTMLInputElement>("LangSmith Workspace ID (optional)")
      .value,
  ).toBe("workspace-a");
  fireEvent.change(screen.getByLabelText("LangSmith Project"), {
    target: { value: "new-project" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await screen.findByRole("alert");
  expect(
    rs.mocked(api.saveTracingProfile).mock.calls[0]![1].providers[0],
  ).toMatchObject({ project: "new-project", workspace_id: "workspace-a" });
  fireEvent.change(screen.getByLabelText("LangSmith Workspace ID (optional)"), {
    target: { value: "workspace-b" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() =>
    expect(rs.mocked(api.saveTracingProfile).mock.calls.length).toBe(2),
  );
  const provider = rs.mocked(api.saveTracingProfile).mock.calls[1]![1]
    .providers[0];
  expect(provider?.workspace_id).toBe("workspace-b");
  expect(provider).not.toHaveProperty("api_key");
});

it("preserves a conflicted profile draft and reopens the latest revision after cancellation", async () => {
  const latest = {
    ...profiles.profiles[0]!,
    name: "Updated elsewhere",
    revision: 4,
  };
  rs.mocked(api.loadTracingProfiles).mockResolvedValue({
    ...profiles,
    can_manage: true,
  });
  rs.mocked(api.saveTracingProfile).mockImplementationOnce(async () => {
    rs.mocked(api.loadTracingProfiles).mockResolvedValue({
      ...profiles,
      can_manage: true,
      profiles: [latest],
    });
    throw new GatewayApiError({
      status: 409,
      code: "revision_conflict",
      message: "Conflict",
      rawMessage: "Conflict",
      params: {},
    });
  });
  rs.mocked(api.saveTracingProfile).mockResolvedValueOnce(latest);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit QA profile" }),
  );
  fireEvent.change(screen.getByLabelText("Profile name"), {
    target: { value: "My draft name" },
  });
  fireEvent.change(screen.getByLabelText("Arize API key"), {
    target: { value: "draft-rotation-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toMatch(/cancel.*reopen/i);
  expect(alert.textContent).not.toContain("Reload saved tracing");
  expect(screen.getByLabelText<HTMLInputElement>("Profile name").value).toBe(
    "My draft name",
  );
  expect(screen.getByLabelText<HTMLInputElement>("Arize API key").value).toBe(
    "draft-rotation-key",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit Updated elsewhere" }),
  );
  expect(screen.getByLabelText<HTMLInputElement>("Profile name").value).toBe(
    "Updated elsewhere",
  );
  expect(screen.getByLabelText<HTMLInputElement>("Arize API key").value).toBe(
    "",
  );
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() =>
    expect(rs.mocked(api.saveTracingProfile).mock.calls.length).toBe(2),
  );
  expect(
    rs.mocked(api.saveTracingProfile).mock.calls[0]![1].expected_revision,
  ).toBe(3);
  expect(
    rs.mocked(api.saveTracingProfile).mock.calls[1]![1].expected_revision,
  ).toBe(4);
});
