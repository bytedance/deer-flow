import { useCallback, useEffect, useState } from "react";
import { Outlet } from "react-router";
import { Toaster } from "sonner";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ArtifactsProvider } from "@/components/workspace/artifacts/context";
import { RightPanelProvider } from "@/components/workspace/right-panel-context";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { WorkspaceTitleBar } from "@/components/workspace/workspace-title-bar";
import { useLocalSettings } from "@/core/settings";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceLayout() {
  const [settings, setSettings] = useLocalSettings();
  const [open, setOpen] = useState(() => !settings.layout.sidebar_collapsed);

  useEffect(() => {
    setOpen(!settings.layout.sidebar_collapsed);
  }, [settings.layout.sidebar_collapsed]);

  const handleOpenChange = useCallback(
    (open: boolean) => {
      setOpen(open);
      setSettings("layout", { sidebar_collapsed: !open });
    },
    [setSettings]
  );

  return (
    <RightPanelProvider>
      <SidebarProvider
        className={cn("h-screen", env.IS_ELECTRON && "pt-10")}
        open={open}
        onOpenChange={handleOpenChange}
      >
        <ArtifactsProvider>
          {env.IS_ELECTRON && <WorkspaceTitleBar />}
          <WorkspaceSidebar />
          <SidebarInset className="min-w-0">
            <PromptInputProvider>
              <Outlet />
            </PromptInputProvider>
          </SidebarInset>
        </ArtifactsProvider>
      </SidebarProvider>
      <Toaster position="top-center" />
    </RightPanelProvider>
  );
}
