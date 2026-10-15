import { cookies } from "next/headers";

import { isAuthDisabledMode } from "@/core/auth/auth-disabled-user";
import { AUTH_REQUEST_TIMEOUT_MS } from "@/core/auth/constants";
import { getGatewayConfig } from "@/core/auth/gateway-config";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { parseWorkspaceCapability } from "./capability";

/** Server capability only: URL selectors cannot enable tenant mode. */
export async function getServerSideWorkspaceCapability() {
  // Gateway startup rejects tenant mode with authentication disabled.
  if (isStaticWebsiteOnly() || isAuthDisabledMode())
    return parseWorkspaceCapability({});
  const session = (await cookies()).get("access_token");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(
      `${getGatewayConfig().internalGatewayUrl}/api/features`,
      {
        headers: session
          ? { Cookie: `access_token=${session.value}` }
          : undefined,
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
      },
    );
    if (!response.ok) throw new Error("Workspace capability unavailable");
    const data: unknown = await response.json();
    controller.signal.throwIfAborted();
    return parseWorkspaceCapability(data);
  } finally {
    clearTimeout(timeout);
  }
}
