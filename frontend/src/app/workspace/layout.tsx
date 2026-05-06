import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { CommandPalette } from "@/components/workspace/command-palette";
import { TenantGuardWrapper } from "@/components/workspace/tenant-guard-wrapper";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { buildLoginUrl, type User } from "@/core/auth/types";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  const authResult = await getServerSideUser();
  let initialUser: User | null = null;
  if (authResult.tag === "authenticated" || authResult.tag === "needs_setup") {
    initialUser = authResult.user;
  } else if (authResult.tag === "unauthenticated") {
    redirect(buildLoginUrl("/workspace"));
  }
  // gateway_unavailable / config_error / system_setup_required: render with null user
  // (backend middleware handles auth enforcement; we just show no user info)

  return (
    <AuthProvider initialUser={initialUser}>
      <QueryClientProvider>
        <TenantGuardWrapper>
          <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
            <WorkspaceSidebar />
            <SidebarInset className="min-w-0">{children}</SidebarInset>
          </SidebarProvider>
          <CommandPalette />
          <Toaster position="top-center" />
        </TenantGuardWrapper>
      </QueryClientProvider>
    </AuthProvider>
  );
}
