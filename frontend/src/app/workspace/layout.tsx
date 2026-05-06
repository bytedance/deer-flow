import Link from "next/link";
import { redirect } from "next/navigation";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { CommandPalette } from "@/components/workspace/command-palette";
import { TenantGuardWrapper } from "@/components/workspace/tenant-guard-wrapper";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";

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

  return (
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
  );
}
