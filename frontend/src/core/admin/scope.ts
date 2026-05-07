import type { User } from "@/core/auth/types";

export function isSystemAdminView(user: Pick<User, "system_role" | "tenant_id"> | null | undefined): boolean {
  return user?.system_role === "admin" && user.tenant_id === "default";
}
