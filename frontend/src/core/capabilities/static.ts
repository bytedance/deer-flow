import catalog from "./builtin.demo.json";
import type { CapabilityInstallation } from "./types";

/** Generated catalog snapshot; refresh with pnpm catalog:sync. */
export const staticCapabilityCatalog = catalog;

export async function staticCapabilityInstallations(
  adapter: string,
  origin: string,
  init?: RequestInit,
): Promise<Response> {
  const paths: Record<string, string> = {
    mcp: "mcp/config",
    business: "mcp/config",
    lark: "integrations/lark/status",
    skills: "skills",
  };
  const path = paths[adapter];
  if (!path)
    return Response.json(
      { detail: "Unknown capability adapter" },
      { status: 404 },
    );
  const response = await globalThis.fetch(
    new URL(`/mock/api/${path}`, origin).href,
    { ...init, method: "GET" },
  );
  if (!response.ok)
    return Response.json(
      { detail: "Demo fixture unavailable" },
      { status: response.status },
    );
  const data = (await response.json()) as {
    mcp_servers?: Record<
      string,
      {
        enabled?: boolean;
        description?: string;
        capability?: { plugin_id?: string };
      }
    >;
    skills?: {
      name: string;
      description: string;
      enabled: boolean;
      category: string;
    }[];
    installed?: boolean;
    manifest_version?: string | null;
  };
  const base = {
    description: "",
    installed: true,
    enabled: null,
    version: null,
    scope: "deployment",
    auth_status: "unknown",
    health: "unknown",
    category: null,
    icon: null,
  };
  let items: CapabilityInstallation[];
  if (adapter === "skills") {
    items = (data.skills ?? []).map((skill) => ({
      ...base,
      id: `skill:${skill.category}:${skill.name}`,
      plugin_id: null,
      adapter,
      name: skill.name,
      reference: skill.name,
      description: skill.description,
      enabled: skill.enabled,
      category: skill.category,
      auth_status: "not_required",
    }));
  } else if (adapter === "lark") {
    items = [
      {
        ...base,
        id: "lark",
        plugin_id: "lark",
        adapter,
        name: "Lark / Feishu",
        reference: "lark",
        installed: data.installed === true,
        version: data.manifest_version ?? null,
        scope: "user",
      },
    ];
  } else {
    items = Object.entries(data.mcp_servers ?? {})
      .filter(
        ([, server]) =>
          adapter !== "business" ||
          ["dingtalk", "wecom", "hubspot"].includes(
            server.capability?.plugin_id ?? "",
          ),
      )
      .map(([name, server]) => ({
        ...base,
        id: `demo:mcp:${encodeURIComponent(name)}`,
        plugin_id: server.capability?.plugin_id ?? null,
        adapter: "mcp",
        name,
        reference: name,
        description: server.description ?? "",
        enabled: server.enabled ?? true,
      }));
  }
  return Response.json({ items, can_manage: false });
}
