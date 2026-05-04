import { fetchGateway } from "../api";
import { getBackendBaseURL } from "../config";

import type {
  AdminStats,
  AuditLogResponse,
  BudgetStatus,
  CostBreakdownItem,
  CostSummary,
  CreateTenantRequest,
  TenantSummary,
  UpdateBudgetRequest,
  UpdateTenantRequest,
  UsageRecord,
} from "./types";

function api(path: string, init?: RequestInit): Promise<Response> {
  return fetchGateway(`${getBackendBaseURL()}${path}`, init);
}

async function parseJSON<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${fallback}: ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

// ── Admin Stats ──

export async function getAdminStats(): Promise<AdminStats> {
  const res = await api("/api/admin/stats");
  return parseJSON(res, "Failed to fetch admin stats");
}

// ── Tenants ──

export async function listTenants(): Promise<TenantSummary[]> {
  const res = await api("/api/admin/tenants");
  return parseJSON(res, "Failed to list tenants");
}

export async function createTenant(req: CreateTenantRequest): Promise<TenantSummary> {
  const res = await api("/api/admin/tenants", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return parseJSON(res, "Failed to create tenant");
}

export async function updateTenant(tenantId: string, req: UpdateTenantRequest): Promise<TenantSummary> {
  const res = await api(`/api/admin/tenants/${encodeURIComponent(tenantId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return parseJSON(res, "Failed to update tenant");
}

// ── Usage ──

export async function getAdminUsage(startDate?: string, endDate?: string): Promise<UsageRecord[]> {
  const params = new URLSearchParams();
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  const qs = params.toString();
  const res = await api(`/api/admin/usage${qs ? `?${qs}` : ""}`);
  return parseJSON(res, "Failed to fetch usage data");
}

// ── Cost ──

export async function getCostSummary(): Promise<CostSummary> {
  const res = await api("/api/cost/summary");
  return parseJSON(res, "Failed to fetch cost summary");
}

export async function getCostBreakdown(startDate?: string, endDate?: string, model?: string): Promise<CostBreakdownItem[]> {
  const params = new URLSearchParams();
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  if (model) params.set("model", model);
  const qs = params.toString();
  const res = await api(`/api/cost/breakdown${qs ? `?${qs}` : ""}`);
  return parseJSON(res, "Failed to fetch cost breakdown");
}

export async function getBudgetStatus(): Promise<BudgetStatus> {
  const res = await api("/api/cost/budget");
  return parseJSON(res, "Failed to fetch budget status");
}

export async function updateBudget(req: UpdateBudgetRequest): Promise<BudgetStatus> {
  const res = await api("/api/cost/budget", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return parseJSON(res, "Failed to update budget");
}

// ── Audit Logs ──

export async function getAdminLogs(params?: {
  tenant_id?: string;
  thread_id?: string;
  direction?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}): Promise<AuditLogResponse> {
  const searchParams = new URLSearchParams();
  if (params?.tenant_id) searchParams.set("tenant_id", params.tenant_id);
  if (params?.thread_id) searchParams.set("thread_id", params.thread_id);
  if (params?.direction) searchParams.set("direction", params.direction);
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);
  if (params?.limit !== undefined) searchParams.set("limit", String(params.limit));
  if (params?.offset !== undefined) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  const res = await api(`/api/admin/logs${qs ? `?${qs}` : ""}`);
  return parseJSON(res, "Failed to fetch audit logs");
}
