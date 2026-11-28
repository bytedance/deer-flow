import type { User } from "@/core/auth/types";
import type { SkillManagementFeature } from "@/core/features/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";

/**
 * Resolve the custom-skill lifecycle permission without changing the global
 * unresolved-permission fallback used by unrelated surfaces.
 */
export function canManageSkills(
  user: Pick<User, "system_role"> | null | undefined,
  feature: SkillManagementFeature | null | undefined,
): boolean {
  if (isStaticWebsiteOnly()) return false;
  if (feature?.lifecycle_permissions === true) {
    return feature.can_manage === true;
  }
  return user?.system_role === "admin";
}

export function canInstallSkillFromSource(
  feature: SkillManagementFeature | null | undefined,
): boolean {
  return (
    !isStaticWebsiteOnly() &&
    feature?.lifecycle_permissions === true &&
    feature.source_install_available === true
  );
}
