import { fetch } from "@/core/api/fetcher";

export interface CapabilityOwner {
  business: string;
  technical: string;
}

export interface CapabilitySummary {
  name: string;
  type: "model" | "skill" | "mcp" | "connector" | "agent";
  display_name: string;
  description: string;
  scope: "GLOBAL" | "TENANT" | "TENANT_OVERRIDE";
  status: "enabled" | "disabled" | "deprecated";
  owner: CapabilityOwner;
  version?: string | null;
  source?: string | null;
  tags: string[];
}

export interface CapabilityChangeRecord {
  timestamp: string;
  actor: string;
  summary: string;
}

export interface CapabilityDetail {
  name: string;
  type: string;
  display_name: string;
  description: string;
  scope: string;
  status: string;
  owner: CapabilityOwner;
  version?: string | null;
  source?: string | null;
  tags: string[];
  extensions: Record<string, unknown>;
  recent_changes: CapabilityChangeRecord[];
}

export interface CapabilityListResponse {
  capabilities: CapabilitySummary[];
  total: number;
  types: string[];
}

export interface TenantCapabilityView {
  name: string;
  type: string;
  scope: string;
  status: string;
  resolution: "inherited" | "overridden" | "tenant_direct";
  config: Record<string, unknown>;
}

export interface ImpactSummary {
  capability: { type: string; name: string };
  scope: string;
  action: string;
  affected_tenants: string[];
  affected_count: number;
  warning_level: "none" | "info" | "warning" | "critical";
  generated_at: string;
}

const TYPE_LABELS: Record<string, string> = {
  model: "模型",
  skill: "技能",
  mcp: "MCP",
  connector: "连接器",
  agent: "Agent",
};

const SCOPE_LABELS: Record<string, string> = {
  GLOBAL: "全局",
  TENANT: "租户",
  TENANT_OVERRIDE: "租户覆盖",
};

const STATUS_LABELS: Record<string, string> = {
  enabled: "已启用",
  disabled: "已禁用",
  deprecated: "已弃用",
};

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type;
}

export function scopeLabel(scope: string): string {
  return SCOPE_LABELS[scope] ?? scope;
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export async function getCapabilities(
  type?: string,
  scope?: string,
): Promise<CapabilityListResponse> {
  const params = new URLSearchParams();
  if (type) params.set("type", type);
  if (scope) params.set("scope", scope);
  const qs = params.toString();
  const url = `/api/capabilities${qs ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch capabilities: ${res.status}`);
  return res.json();
}

export async function getCapabilityDetail(
  type: string,
  name: string,
): Promise<CapabilityDetail> {
  const res = await fetch(`/api/capabilities/${type}/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(`Failed to fetch capability detail: ${res.status}`);
  return res.json();
}

export async function getCapabilityImpact(
  type: string,
  name: string,
  action: string = "deactivate",
): Promise<ImpactSummary> {
  const res = await fetch(
    `/api/capabilities/${type}/${encodeURIComponent(name)}/impact?action=${action}`,
  );
  if (!res.ok) throw new Error(`Failed to fetch impact: ${res.status}`);
  return res.json();
}

export async function getCapabilityAudit(
  type: string,
  name: string,
  limit: number = 20,
): Promise<Record<string, unknown>[]> {
  const res = await fetch(
    `/api/capabilities/${type}/${encodeURIComponent(name)}/audit?limit=${limit}`,
  );
  if (!res.ok) throw new Error(`Failed to fetch audit: ${res.status}`);
  return res.json();
}

export async function resolveCapabilityForTenant(
  tenantId: string,
  type: string,
  name: string,
): Promise<TenantCapabilityView> {
  const res = await fetch(
    `/api/capabilities/resolve/${tenantId}/${type}/${encodeURIComponent(name)}`,
  );
  if (!res.ok) throw new Error(`Failed to resolve capability: ${res.status}`);
  return res.json();
}
