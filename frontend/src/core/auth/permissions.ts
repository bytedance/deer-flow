import type { User } from "./types";

/**
 * Route permissions surfaced by `GET /api/v1/auth/me` (RFC #4063 Phase 4).
 * Kept in lockstep with `Permissions` in `backend/app/gateway/authz.py`.
 */
export const PERMISSIONS = {
  THREADS_DELETE: "threads:delete",
  RUNS_CANCEL: "runs:cancel",
} as const;

/**
 * Whether the current user may perform a route-permission-gated action.
 *
 * The permission list is advisory UI state, not enforcement: a missing list
 * (pre-Phase-4 backend, or a credential that never resolved permissions —
 * serialized as `null`) or a not-yet-loaded user is treated as permissive so
 * a mixed old-backend/new-frontend deploy never hides actions the caller can
 * still perform. The Gateway's `@require_permission` route guards remain the
 * single enforcement point.
 */
export function hasPermission(
  user: Pick<User, "permissions"> | null | undefined,
  permission: string,
): boolean {
  if (user?.permissions == null) {
    return true;
  }
  return user.permissions.includes(permission);
}
