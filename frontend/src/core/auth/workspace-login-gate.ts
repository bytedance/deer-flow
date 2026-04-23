/**
 * Set from ``/user/workspace-auth/config`` after the workspace shell mounts.
 * Drives ``gatewayFetch`` credentials and the OA session bootstrap.
 */

let workspaceLoginRequired = false;

export function setWorkspaceLoginRequired(value: boolean): void {
  workspaceLoginRequired = value;
}

export function isWorkspaceLoginRequiredSync(): boolean {
  return workspaceLoginRequired;
}
