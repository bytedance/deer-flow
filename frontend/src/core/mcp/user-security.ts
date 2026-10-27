import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ToolResource = {
  resource: "tool" | "mcp_server" | "skill";
  target: string;
  label?: string;
  allowed: boolean;
  credential_supported?: boolean;
  server?: string;
};
export type UserToolSecurity = {
  enabled: boolean;
  admin: boolean;
  resources: ToolResource[];
  credentials: string[];
};
export type UserToolGrants = {
  resources?: ToolResource[];
  email: string;
  admin: boolean;
  grants: Pick<ToolResource, "resource" | "target">[];
  direct_grants: Pick<ToolResource, "resource" | "target">[];
  denied: Pick<ToolResource, "resource" | "target">[];
  groups: { id: string; name: string }[];
};
export type PersonalOverride = "inherit" | "allow" | "deny";
export type UserGroup = { id: string; name: string; member_count: number };
export type UserGroupDetail = {
  id: string;
  name: string;
  members: { id: string; email: string | null }[];
  grants: Pick<ToolResource, "resource" | "target">[];
};

export async function securityRequest<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/user-security${path}`,
    {
      method,
      ...(body === undefined
        ? {}
        : {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
    },
  );
  if (!response.ok) {
    // Do not echo request/validation payloads that might contain a credential.
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
