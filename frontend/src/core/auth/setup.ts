import { parseAuthError } from "./types";

export type SetupStatusResponse = {
  needs_setup?: boolean;
  registration_enabled?: boolean;
};

export type SetupStatusCheck = {
  checked: boolean;
  status: SetupStatusResponse | null;
};

export const setupStatusFetchInit = {
  cache: "no-store",
  credentials: "include",
} satisfies RequestInit;

export async function fetchSetupStatus(): Promise<SetupStatusResponse> {
  const response = await fetch(
    "/api/v1/auth/setup-status",
    setupStatusFetchInit,
  );
  if (!response.ok) {
    throw new Error(`setup-status failed: ${response.status}`);
  }
  return (await response.json()) as SetupStatusResponse;
}

export function isSystemAlreadyInitializedError(data: unknown): boolean {
  return parseAuthError(data).code === "system_already_initialized";
}

export function canCreateRegularAccount(check: SetupStatusCheck): boolean {
  // registration_enabled is absent on older Gateways; treat that as allowed so
  // the signup entry only disappears when the backend actively closes it.
  return (
    check.checked &&
    check.status?.needs_setup !== true &&
    check.status?.registration_enabled !== false
  );
}
