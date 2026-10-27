import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { UserToolSecurityPanel } from "@/components/workspace/settings/user-tool-security";
import { I18nProvider } from "@/core/i18n/context";
import { securityRequest, type ToolResource } from "@/core/mcp/user-security";

rs.mock("@/core/mcp/user-security", () => ({ securityRequest: rs.fn() }));
const identity = rs.hoisted(() => ({ user: { id: "alice" } }));
rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: () => identity }));
const request = rs.mocked(securityRequest);
beforeEach(() => {
  document.cookie = "locale=en-US; path=/";
  request.mockReset();
  identity.user = { id: "alice" };
});
afterEach(cleanup);

function mount(
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  locale: "en-US" | "zh-CN" = "en-US",
) {
  document.cookie = `locale=${locale}; path=/`;
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale={locale}>
        <UserToolSecurityPanel />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

it("keeps grant management out of a normal user's settings and clears saved credentials", async () => {
  request.mockImplementation(async (path) =>
    path === "/me"
      ? {
          enabled: true,
          admin: false,
          resources: [
            {
              resource: "mcp_server",
              target: "crm",
              allowed: true,
              credential_supported: true,
            },
          ],
          credentials: [],
        }
      : { configured: true },
  );
  mount();
  const input = await screen.findByLabelText("Credential crm");
  expect(screen.queryByText("User extension access")).toBeNull();
  expect(screen.queryByText("User groups")).toBeNull();
  expect(request.mock.calls.some(([path]) => path === "/groups")).toBe(false);
  fireEvent.change(input, { target: { value: "Bearer private-token" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/credentials/crm", "PUT", {
      credential: "Bearer private-token",
    }),
  );
  await waitFor(() => expect((input as HTMLInputElement).value).toBe(""));
});

it("discards credential drafts and administrator state when the account changes", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  request.mockImplementation(async () => ({
    enabled: true,
    admin: identity.user.id === "alice",
    resources: [
      {
        resource: "mcp_server",
        target: "crm",
        allowed: true,
        credential_supported: true,
      },
    ],
    credentials: [],
  }));
  const view = mount(client);
  fireEvent.change(await screen.findByLabelText("Credential crm"), {
    target: { value: "alice-draft" },
  });
  expect(screen.getByText("User extension access")).toBeTruthy();
  identity.user = { id: "bob" };
  view.rerender(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale="en-US">
        <UserToolSecurityPanel />
      </I18nProvider>
    </QueryClientProvider>,
  );
  expect(screen.queryByText("User extension access")).toBeNull();
  const input = await screen.findByLabelText("Credential crm");
  expect((input as HTMLInputElement).value).toBe("");
  expect(screen.queryByText("User extension access")).toBeNull();
});

it("binds personal overrides to the loaded user and shows inherited access", async () => {
  let mode = "inherit";
  request.mockImplementation(async (path, _method, body) => {
    if (path === "/me")
      return {
        enabled: true,
        admin: true,
        resources: [{ resource: "tool", target: "custom_tool", allowed: true }],
        credentials: [],
      };
    if (path.startsWith("/grants?"))
      return {
        email: "alice@example.org",
        admin: false,
        grants:
          mode === "deny" ? [] : [{ resource: "tool", target: "custom_tool" }],
        direct_grants:
          mode === "allow" ? [{ resource: "tool", target: "custom_tool" }] : [],
        denied:
          mode === "deny" ? [{ resource: "tool", target: "custom_tool" }] : [],
        groups: [{ id: "engineering", name: "Engineering" }],
      };
    if (path === "/groups") return { groups: [] };
    mode = (body as { mode: string }).mode;
    return { mode };
  });
  mount();
  fireEvent.change(await screen.findByLabelText("User email"), {
    target: { value: "alice@example.org" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load user" }));
  const override = await screen.findByRole("combobox", {
    name: "Personal override custom_tool",
  });
  expect((override as HTMLSelectElement).value).toBe("inherit");
  expect(screen.getByText("Engineering")).toBeTruthy();
  expect(screen.getByText("Allowed")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("User email"), {
    target: { value: "someone-else@example.org" },
  });
  fireEvent.change(override, { target: { value: "deny" } });
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/overrides", "PUT", {
      email: "alice@example.org",
      resource: "tool",
      target: "custom_tool",
      mode: "deny",
    }),
  );
  await screen.findByText("Denied");
  await waitFor(() =>
    expect((override as HTMLSelectElement).disabled).toBe(false),
  );
  fireEvent.change(override, { target: { value: "allow" } });
  await waitFor(() =>
    expect((override as HTMLSelectElement).value).toBe("allow"),
  );
  await screen.findByText("Allowed");
  await waitFor(() =>
    expect((override as HTMLSelectElement).disabled).toBe(false),
  );
  fireEvent.change(override, { target: { value: "inherit" } });
  await waitFor(() =>
    expect((override as HTMLSelectElement).value).toBe("inherit"),
  );
  expect(screen.getByText("Allowed")).toBeTruthy();
});

function mockGroups(
  resources: ToolResource[] = [
    { resource: "tool", target: "custom_tool", allowed: true },
  ],
) {
  let groups = [{ id: "eng", name: "Engineering", member_count: 1 }];
  let members = [{ id: "member-1", email: "member@example.org" }];
  let grants: { resource: string; target: string }[] = [];
  request.mockImplementation(async (path, method = "GET", body) => {
    const values = body as Record<string, string | boolean> | undefined;
    if (path === "/me")
      return {
        enabled: true,
        admin: true,
        resources,
        credentials: [],
      };
    if (path === "/groups" && method === "POST") {
      const group = { id: "new", name: String(values?.name), member_count: 0 };
      groups.push(group);
      return group;
    }
    if (path === "/groups") return { groups: [...groups] };
    const id = path.split("/")[2];
    if (path.endsWith("/members") && method === "POST") {
      members = [...members, { id: "member-2", email: String(values?.email) }];
      return { member: true };
    }
    if (path.includes("/members/") && method === "DELETE") {
      members = members.filter((member) => member.id !== path.split("/")[4]);
      return { member: false };
    }
    if (path.endsWith("/grants")) {
      grants = values?.allowed
        ? [{ resource: String(values.resource), target: String(values.target) }]
        : [];
      return { allowed: values?.allowed };
    }
    if (method === "PATCH") {
      groups = groups.map((group) =>
        group.id === id ? { ...group, name: String(values?.name) } : group,
      );
      return groups.find((group) => group.id === id);
    }
    if (method === "DELETE") {
      groups = groups.filter((group) => group.id !== id);
      return { deleted: true };
    }
    return { ...groups.find((group) => group.id === id), members, grants };
  });
}

it("creates, selects, renames and confirms deletion of groups", async () => {
  mockGroups();
  mount();
  fireEvent.change(await screen.findByLabelText("New group name"), {
    target: { value: "Support" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create group" }));
  const name = await screen.findByLabelText("Group name");
  expect((name as HTMLInputElement).value).toBe("Support");
  fireEvent.change(name, { target: { value: "Customer support" } });
  fireEvent.click(screen.getByRole("button", { name: "Rename group" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/groups/new", "PATCH", {
      name: "Customer support",
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Delete group" })
        .disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
  expect(screen.getByRole("alertdialog")).toBeTruthy();
  expect(
    request.mock.calls.some(
      ([path, method]) => path === "/groups/new" && method === "DELETE",
    ),
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Confirm deletion" }));
  await waitFor(() => expect(screen.queryByLabelText("Group name")).toBeNull());
  fireEvent.change(screen.getByLabelText("Select group"), {
    target: { value: "eng" },
  });
  await waitFor(() =>
    expect(screen.getByLabelText<HTMLInputElement>("Group name").value).toBe(
      "Engineering",
    ),
  );
});

it("adds and removes group members and changes exact grants", async () => {
  mockGroups();
  mount();
  const select = await screen.findByLabelText("Select group");
  await screen.findByRole("option", { name: /Engineering/ });
  fireEvent.change(select, { target: { value: "eng" } });
  fireEvent.change(await screen.findByLabelText("Member email"), {
    target: { value: "second@example.org" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add member" }));
  await screen.findByText("second@example.org");
  fireEvent.click(
    screen.getByRole("button", { name: "Remove member member@example.org" }),
  );
  await waitFor(() =>
    expect(screen.queryByText("member@example.org")).toBeNull(),
  );
  fireEvent.click(
    screen.getByRole("switch", { name: "Group access custom_tool" }),
  );
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/groups/eng/grants", "PUT", {
      resource: "tool",
      target: "custom_tool",
      allowed: true,
    }),
  );
});

it("resets group selection and isolates cached groups on account changes", async () => {
  mockGroups();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const view = mount(client);
  await screen.findByRole("option", { name: /Engineering/ });
  fireEvent.change(screen.getByLabelText("Select group"), {
    target: { value: "eng" },
  });
  await screen.findByLabelText("Group name");
  identity.user = { id: "bob" };
  request.mockImplementation(async (path) =>
    path === "/me"
      ? { enabled: true, admin: true, resources: [], credentials: [] }
      : { groups: [] },
  );
  view.rerender(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale="en-US">
        <UserToolSecurityPanel />
      </I18nProvider>
    </QueryClientProvider>,
  );
  await screen.findByLabelText("Select group");
  expect(screen.queryByLabelText("Group name")).toBeNull();
  expect(screen.queryByRole("option", { name: /Engineering/ })).toBeNull();
});

it("does not expose the previous group's mutations while the next group loads and locks pending changes", async () => {
  let resolveSupport!: (value: unknown) => void;
  const support = new Promise((resolve) => {
    resolveSupport = resolve;
  });
  let resolveGrant!: (value: unknown) => void;
  const grant = new Promise((resolve) => {
    resolveGrant = resolve;
  });
  request.mockImplementation(async (path, method = "GET") => {
    if (path === "/me")
      return {
        enabled: true,
        admin: true,
        resources: [{ resource: "tool", target: "custom_tool", allowed: true }],
        credentials: [],
      };
    if (path === "/groups")
      return {
        groups: [
          { id: "eng", name: "Engineering", member_count: 0 },
          { id: "support", name: "Support", member_count: 0 },
        ],
      };
    if (method === "PUT") return grant;
    if (path === "/groups/support") return support;
    return { id: "eng", name: "Engineering", members: [], grants: [] };
  });
  mount();
  await screen.findByRole("option", { name: /Engineering/ });
  const select = screen.getByLabelText<HTMLSelectElement>("Select group");
  fireEvent.change(select, { target: { value: "eng" } });
  await screen.findByRole("switch", { name: "Group access custom_tool" });
  fireEvent.change(select, { target: { value: "support" } });
  expect(
    screen.queryByRole("switch", { name: "Group access custom_tool" }),
  ).toBeNull();
  expect(screen.queryByLabelText("Group name")).toBeNull();
  resolveSupport({ id: "support", name: "Support", members: [], grants: [] });
  const toggle = await screen.findByRole<HTMLButtonElement>("switch", {
    name: "Group access custom_tool",
  });
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/groups/support/grants", "PUT", {
      resource: "tool",
      target: "custom_tool",
      allowed: true,
    }),
  );
  expect(select.disabled).toBe(true);
  expect(toggle.disabled).toBe(true);
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Delete group" })
      .disabled,
  ).toBe(true);
  resolveGrant({ allowed: true });
  await waitFor(() => expect(select.disabled).toBe(false));
});

it("shows skill names and categories while granting the exact group resource", async () => {
  mockGroups([
    {
      resource: "skill",
      target: "custom/expense-report",
      label: "Expense report",
      allowed: true,
    },
  ]);
  mount();
  await screen.findByRole("option", { name: /Engineering/ });
  fireEvent.change(screen.getByLabelText("Select group"), {
    target: { value: "eng" },
  });
  expect(await screen.findByText("Expense report")).toBeTruthy();
  expect(screen.getByText("Skill")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("switch", { name: "Group access custom/expense-report" }),
  );
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/groups/eng/grants", "PUT", {
      resource: "skill",
      target: "custom/expense-report",
      allowed: true,
    }),
  );
});

it("shows skill names while sending the exact personal override target", async () => {
  request.mockImplementation(async (path) => {
    if (path === "/me")
      return {
        enabled: true,
        admin: true,
        resources: [
          {
            resource: "skill",
            target: "custom/expense-report",
            label: "Expense report",
            allowed: true,
          },
        ],
        credentials: [],
      };
    if (path === "/groups") return { groups: [] };
    return {
      email: "alice@example.org",
      admin: false,
      grants: [],
      direct_grants: [],
      denied: [],
      groups: [],
    };
  });
  mount();
  fireEvent.change(await screen.findByLabelText("User email"), {
    target: { value: "alice@example.org" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load user" }));
  expect(await screen.findByText("Expense report")).toBeTruthy();
  expect(screen.getByText("Skill")).toBeTruthy();
  fireEvent.change(
    screen.getByRole("combobox", {
      name: "Personal override custom/expense-report",
    }),
    { target: { value: "allow" } },
  );
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/overrides", "PUT", {
      email: "alice@example.org",
      resource: "skill",
      target: "custom/expense-report",
      mode: "allow",
    }),
  );
});

it("lists authorized skills by name without creating a credential form", async () => {
  request.mockResolvedValue({
    enabled: true,
    admin: false,
    resources: [
      {
        resource: "skill",
        target: "custom/expense-report",
        label: "Expense report",
        allowed: true,
      },
    ],
    credentials: [],
  });
  mount();
  expect(await screen.findByText("Expense report")).toBeTruthy();
  expect(screen.getByText("Skill")).toBeTruthy();
  expect(
    screen.queryByLabelText("Credential custom/expense-report"),
  ).toBeNull();
});

it.each(["en-US", "zh-CN"] as const)(
  "explains default access when no extensions need permissions in %s",
  async (locale) => {
    request.mockResolvedValue({
      enabled: true,
      admin: false,
      resources: [],
      credentials: [],
    });
    mount(undefined, locale);
    const copy =
      locale === "en-US"
        ? "No additional extension permissions to configure. Built-in tools and skills are available by default."
        : "暂无需要配置权限的新增扩展。内置工具和技能默认可用。";
    expect(await screen.findByText(copy)).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
  },
);

it("uses the target user's private skill catalog for personal grants only", async () => {
  request.mockImplementation(async (path) => {
    if (path === "/me")
      return {
        enabled: true,
        admin: true,
        credentials: [],
        resources: [
          {
            resource: "skill",
            target: "custom/admin-only",
            label: "Admin private skill",
            allowed: true,
          },
        ],
      };
    if (path === "/groups")
      return { groups: [{ id: "eng", name: "Engineering", member_count: 0 }] };
    if (path === "/groups/eng")
      return { id: "eng", name: "Engineering", members: [], grants: [] };
    return {
      email: "target@example.org",
      admin: false,
      grants: [],
      direct_grants: [],
      denied: [],
      groups: [],
      resources: [
        {
          resource: "skill",
          target: "custom/target-only",
          label: "Target private skill",
          allowed: false,
        },
      ],
    };
  });
  mount();
  fireEvent.change(await screen.findByLabelText("User email"), {
    target: { value: "target@example.org" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load user" }));
  expect(await screen.findByText("Target private skill")).toBeTruthy();
  expect(
    screen.queryByRole("combobox", {
      name: "Personal override custom/admin-only",
    }),
  ).toBeNull();
  fireEvent.change(
    screen.getByRole("combobox", {
      name: "Personal override custom/target-only",
    }),
    { target: { value: "allow" } },
  );
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/overrides", "PUT", {
      email: "target@example.org",
      resource: "skill",
      target: "custom/target-only",
      mode: "allow",
    }),
  );
  await screen.findByRole("option", { name: /Engineering/ });
  fireEvent.change(screen.getByLabelText("Select group"), {
    target: { value: "eng" },
  });
  expect(
    await screen.findByRole("switch", {
      name: "Group access custom/admin-only",
    }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("switch", { name: "Group access custom/target-only" }),
  ).toBeNull();
});

it("does not fall back to the administrator's catalog when the target catalog is empty", async () => {
  request.mockImplementation(async (path) => {
    if (path === "/me")
      return {
        enabled: true,
        admin: true,
        credentials: [],
        resources: [
          { resource: "skill", target: "custom/admin-only", allowed: true },
        ],
      };
    if (path === "/groups") return { groups: [] };
    return {
      email: "target@example.org",
      admin: false,
      grants: [],
      direct_grants: [],
      denied: [],
      groups: [],
      resources: [],
    };
  });
  mount();
  fireEvent.change(await screen.findByLabelText("User email"), {
    target: { value: "target@example.org" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load user" }));
  await screen.findByText("target@example.org");
  expect(
    screen.queryByRole("combobox", {
      name: "Personal override custom/admin-only",
    }),
  ).toBeNull();
});
