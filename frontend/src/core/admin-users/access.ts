import { isStaticWebsiteOnly } from "@/core/static-mode";

import type { User } from "../auth/types";

const SYNTHETIC_USER_IDS = new Set(["default", "static-website-user"]);

/**
 * The auth-disabled and static-site fallbacks deliberately look like admins so
 * the rest of the workspace remains usable. They are not real accounts and
 * must never expose user-management controls.
 */
export function canManageAdminUsers(user: User | null): boolean {
  return (
    !isStaticWebsiteOnly() &&
    user?.system_role === "admin" &&
    !SYNTHETIC_USER_IDS.has(user.id)
  );
}
