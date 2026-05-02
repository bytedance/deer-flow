export const DEFAULT_TENANT_ID = "default";

export const TENANT_STORAGE_KEY = "deerflow.tenant-id";

export const TENANT_SEARCH_PARAM = "tenant";

/** Same regex as backend: letters, digits, hyphens only (no path traversal) */
export const TENANT_ID_PATTERN = /^[A-Za-z0-9-]+$/;

export function validateTenantId(id: string): string {
  if (!TENANT_ID_PATTERN.test(id) || id.length === 0) {
    throw new Error(
      `Invalid tenant ID "${id}": must contain only letters, digits, and hyphens.`,
    );
  }
  return id;
}
