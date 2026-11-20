"use client";

import { PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

export function WorkspaceSidebarTrigger({
  className,
  onClick,
  ...props
}: React.ComponentProps<typeof Button>) {
  const { isMobile, open, openMobile, toggleSidebar } = useSidebar();
  const expanded = isMobile ? openMobile : open;

  return (
    <Button
      type="button"
      data-sidebar="trigger"
      data-slot="sidebar-trigger"
      variant="ghost"
      size="icon"
      className={cn("size-7 opacity-50 hover:opacity-100", className)}
      {...props}
      aria-expanded={expanded}
      aria-haspopup={isMobile ? "dialog" : undefined}
      onClick={(event) => {
        onClick?.(event);
        if (event.defaultPrevented) return;
        // Touch browsers need an explicit focus target for drawer dismissal.
        if (isMobile && !openMobile) event.currentTarget.focus();
        toggleSidebar();
      }}
    >
      {expanded ? <PanelLeftCloseIcon /> : <PanelLeftOpenIcon />}
      <span className="sr-only">Toggle Sidebar</span>
    </Button>
  );
}
