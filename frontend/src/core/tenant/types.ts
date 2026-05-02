export const DEFAULT_TENANT_ID = "default";

export const TENANT_STORAGE_KEY = "deerflow.tenant-id";

export const TENANT_SEARCH_PARAM = "tenant";

/** Same regex as backend: letters, digits, hyphens only (no path traversal) */
export const TENANT_ID_PATTERN = /^[A-Za-z0-9-]+$/;

export function validateTenantId(id: string): string {
  if (!TENANT_ID_PATTERN.test(id) || id.length === 0) {
    return DEFAULT_TENANT_ID;
  }
  return id;
}
