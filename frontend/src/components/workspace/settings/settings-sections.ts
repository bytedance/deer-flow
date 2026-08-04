import type { User } from "@/core/auth/types";

export type VisibleSettingsSection =
  | "account"
  | "appearance"
  | "notification"
  | "channels"
  | "integrations"
  | "memory"
  | "tools"
  | "skills";

const USER_SECTIONS: VisibleSettingsSection[] = [
  "account",
  "appearance",
  "notification",
  "channels",
  "integrations",
  "memory",
  "tools",
  "skills",
];

export function getVisibleSettingsSectionIds(
  role: User["system_role"] | undefined,
): VisibleSettingsSection[] {
  return role === "admin" ? ["account"] : USER_SECTIONS;
}
