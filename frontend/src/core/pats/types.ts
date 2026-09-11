export const PAT_SCOPES = [
  "threads:read",
  "threads:write",
  "threads:delete",
  "runs:create",
  "runs:read",
  "runs:cancel",
] as const;

export type PatScope = (typeof PAT_SCOPES)[number];

export type PatSummary = {
  id: string;
  name: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
  revoked_at: string | null;
};

// Explicit field list: the create response (PATCreatedResponse) returns only
// these -- it deliberately omits the audit fields PatSummary carries.
export type PatCreated = {
  id: string;
  name: string;
  scopes: string[];
  expires_at: string | null;
  created_at: string;
  token: string;
};

export type CreatePatRequest = {
  name: string;
  scopes: string[];
  expires_in_days: number | null;
};
