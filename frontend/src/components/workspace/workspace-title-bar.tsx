import { PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";
import { useLocation } from "react-router";

import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { env } from "@/env";

import { useRightPanel } from "./right-panel-context";

export function WorkspaceTitleBar() {
  const { open: rightPanelOpen, setOpen: setRightPanelOpen } = useRightPanel();
  const location = useLocation();
  const isOnChatPage = location.pathname.startsWith("/workspace/chats/");

  if (!env.IS_ELECTRON) return null;

  return (
    <div
      className="fixed top-0 right-0 left-0 z-50 flex h-10 select-none items-center border-b border-border/50 bg-[rgb(21,21,21)] backdrop-blur-sm"
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      style={{ WebkitAppRegion: "drag" } as any}
    >
      {/* Space for macOS traffic lights */}
      <div className="w-20 shrink-0" />
      {/* Brand */}
      <span className="text-primary mr-1 font-serif text-sm">Thinktank.ai</span>
      {/* Left panel (sidebar) trigger */}
      <div
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        style={{ WebkitAppRegion: "no-drag" } as any}
      >
        <SidebarTrigger className="h-7 w-7" />
      </div>
      {/* Drag spacer */}
      <div className="flex-1" />
      {/* Right panel toggle (only on chat pages) */}
      {isOnChatPage && (
        <div
          className="mr-2"
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          style={{ WebkitAppRegion: "no-drag" } as any}
        >
          <Button
            className="size-7 opacity-50 hover:opacity-100"
            size="icon"
            variant="ghost"
            onClick={() => setRightPanelOpen(!rightPanelOpen)}
          >
            {rightPanelOpen ? (
              <PanelLeftCloseIcon className="size-3.5" />
            ) : (
              <PanelLeftOpenIcon className="size-3.5" />
            )}
            <span className="sr-only">Toggle right panel</span>
          </Button>
        </div>
      )}
    </div>
  );
}
