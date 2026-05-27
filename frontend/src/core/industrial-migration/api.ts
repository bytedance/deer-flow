import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

export interface MigrationStatus {
  tenant_id: string;
  prompted: boolean;
  completed: boolean;
  accepted: boolean;
  prompted_at: string | null;
  completed_at: string | null;
}

export interface MigrationResult {
  tenant_id: string;
  enabled_count: number;
  skill_names: string[];
}

export interface DeclineResult {
  tenant_id: string;
  message: string;
}

async function _gateway<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchGateway(`${getBackendBaseURL()}${path}`, init);
  if (!res.ok) {
    const detail = await res.json().catch(() => res.statusText);
    throw new Error(
      `Migration API ${init?.method ?? "GET"} ${path} failed: ${res.status} ${JSON.stringify(detail)}`,
    );
  }
  return (await res.json()) as T;
}

export async function getMigrationStatus(
  tenantId: string,
): Promise<MigrationStatus> {
  return _gateway<MigrationStatus>(
    `/api/tenants/${encodeURIComponent(tenantId)}/migration-status`,
  );
}

export async function markMigrationPrompted(
  tenantId: string,
): Promise<MigrationStatus> {
  return _gateway<MigrationStatus>(
    `/api/tenants/${encodeURIComponent(tenantId)}/mark-migration-prompted`,
    { method: "POST" },
  );
}

export async function acceptMigration(
  tenantId: string,
): Promise<MigrationResult> {
  return _gateway<MigrationResult>(
    `/api/tenants/${encodeURIComponent(tenantId)}/migrate-industrial`,
    { method: "POST" },
  );
}

export async function declineMigration(
  tenantId: string,
): Promise<DeclineResult> {
  return _gateway<DeclineResult>(
    `/api/tenants/${encodeURIComponent(tenantId)}/decline-migration`,
    { method: "POST" },
  );
}
