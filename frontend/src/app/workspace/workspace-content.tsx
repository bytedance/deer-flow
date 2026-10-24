import { cookies } from "next/headers";

import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { getServerSideWorkspaceCapability } from "@/core/workspaces/server";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function WorkspaceContent({
  children,
  gatewayUnavailable = false,
}: Readonly<{
  children: React.ReactNode;
  gatewayUnavailable?: boolean;
}>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );
  // An unknown/unavailable capability cannot silently mount a legacy shell.
  const capability = gatewayUnavailable
    ? null
    : await getServerSideWorkspaceCapability().catch(() => null);
  return (
    <WorkspaceShell
      capability={capability}
      initialSidebarOpen={initialSidebarOpen}
      gatewayUnavailable={gatewayUnavailable}
    >
      {children}
    </WorkspaceShell>
  );
}
