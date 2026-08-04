import type { User } from "./types";

export function getWorkspaceHomePath(
  role: User["system_role"],
): "/workspace/admin" | "/workspace/chats/new" {
  return role === "admin" ? "/workspace/admin" : "/workspace/chats/new";
}
