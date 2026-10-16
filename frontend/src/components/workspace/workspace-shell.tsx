"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { Button } from "@/components/ui/button";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ExtensionPageBootstrap } from "@/core/extensions/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";
import type { WorkspaceCapability } from "@/core/workspaces/capability";
import {
  WorkspaceContentBoundary,
  WorkspaceProvider,
  useWorkspaceContext,
} from "@/core/workspaces/context";

import { CommandPalette } from "./command-palette";
import { GatewayOfflineBanner } from "./gateway-offline-banner";
import { ModelLoadErrorBanner } from "./model-load-error-banner";
import { SettingsDialogHost } from "./settings";
import { WorkspaceSettingsDeepLink } from "./workspace-settings-deep-link";
import { WorkspaceSidebar } from "./workspace-sidebar";

type ShellProps = Readonly<{
  children: ReactNode;
  initialSidebarOpen?: boolean;
  gatewayUnavailable?: boolean;
}>;

function ConfirmedWorkspaceShell({
  children,
  initialSidebarOpen,
  gatewayUnavailable = false,
}: ShellProps) {
  const context = useWorkspaceContext();
  const cacheKey = context
    ? (context.state.active?.cacheKey ?? "unconfirmed-workspace")
    : undefined;
  const content = (
    <>
      <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
        <WorkspaceSidebar />
        <SidebarInset className="min-w-0">
          <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
          <WorkspaceContentBoundary>
            <ModelLoadErrorBanner gatewayUnavailable={gatewayUnavailable} />
            {children}
          </WorkspaceContentBoundary>
        </SidebarInset>
      </SidebarProvider>
      <WorkspaceContentBoundary>
        <ExtensionPageBootstrap />
        <CommandPalette />
        <SettingsDialogHost />
        <WorkspaceSettingsDeepLink />
      </WorkspaceContentBoundary>
      <Toaster position="top-center" />
    </>
  );
  // Legacy account preferences must not be copied into a team. Scoped preference
  // policy remains an M5 gate; do not start the account synchronizer in tenant mode.
  return (
    <QueryClientProvider cacheKey={cacheKey}>
      {context ? (
        content
      ) : (
        <UserPreferencesBoundary>{content}</UserPreferencesBoundary>
      )}
    </QueryClientProvider>
  );
}

/** The server alone selects legacy versus scoped mode; metadata confirms the actor. */
export function WorkspaceShell({
  capability,
  gatewayUnavailable = false,
  ...props
}: ShellProps & { capability: WorkspaceCapability | null }) {
  const { t } = useI18n();
  const router = useRouter();
  if (!capability || (capability.enabled && !capability.available)) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-6">
        <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
        <p role="alert" className="text-muted-foreground text-sm">
          {t.workspace.spaceSwitcher.error}
        </p>
        <Button onClick={() => router.refresh()}>
          {t.workspace.spaceSwitcher.retry}
        </Button>
        <Button variant="ghost" asChild>
          <Link href="/login" prefetch={false}>
            {t.login.signIn}
          </Link>
        </Button>
      </main>
    );
  }
  return (
    <WorkspaceProvider enabled={capability.enabled}>
      <ConfirmedWorkspaceShell
        gatewayUnavailable={gatewayUnavailable}
        {...props}
      />
    </WorkspaceProvider>
  );
}
