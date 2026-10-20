"use client";

import { createContext, useContext, useRef, type ReactNode } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Sidebar, useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

const ExpandedContext = createContext<boolean | undefined>(undefined);

// Workspace content follows the surface it is rendered in, independently of
// the saved desktop preference owned by SidebarProvider.
export function useWorkspaceSidebarExpanded() {
  const { open } = useSidebar();
  return useContext(ExpandedContext) ?? open;
}

function Presentation({
  expanded,
  children,
}: {
  expanded: boolean | undefined;
  children: ReactNode;
}) {
  return (
    <ExpandedContext.Provider value={expanded}>
      {children}
    </ExpandedContext.Provider>
  );
}

export function WorkspaceSidebarFrame({
  children,
  collapsible = "icon",
  variant = "sidebar",
  side = "left",
  className,
  style,
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { isMobile, open, openMobile, setOpenMobile } = useSidebar();
  const railRef = useRef<HTMLDivElement>(null);

  if (!isMobile || collapsible !== "icon" || open) {
    return (
      <Sidebar
        collapsible={collapsible}
        variant={variant}
        side={side}
        className={className}
        style={style}
        {...props}
      >
        <Presentation
          expanded={isMobile && collapsible !== "none" ? openMobile : undefined}
        >
          {children}
        </Presentation>
      </Sidebar>
    );
  }

  return (
    <Sheet open={openMobile} onOpenChange={setOpenMobile}>
      {/* Keep the gap while the modal is open so the page does not reflow. */}
      <div
        className="w-(--sidebar-width-icon) shrink-0"
        style={style}
        {...props}
      >
        {!openMobile && (
          <div
            ref={railRef}
            data-sidebar="sidebar"
            data-slot="sidebar"
            data-state="collapsed"
            data-collapsible="icon"
            data-variant={variant}
            data-side={side}
            className={cn(
              "group bg-sidebar text-sidebar-foreground fixed inset-y-0 z-10 flex h-svh w-(--sidebar-width-icon) flex-col",
              side === "left" ? "left-0 border-r" : "right-0 border-l",
              className,
            )}
          >
            <Presentation expanded={false}>{children}</Presentation>
          </div>
        )}
      </div>
      <SheetContent
        data-sidebar="sidebar"
        data-slot="sidebar"
        data-mobile="true"
        side={side}
        className="bg-sidebar text-sidebar-foreground w-(--sidebar-width) gap-0 p-0 [&>button]:hidden"
        style={{ "--sidebar-width": "18rem" } as React.CSSProperties}
        onCloseAutoFocus={(event) => {
          const trigger = railRef.current?.querySelector<HTMLButtonElement>(
            '[data-sidebar="trigger"]',
          );
          if (trigger) {
            event.preventDefault();
            trigger.focus();
          }
        }}
      >
        <SheetHeader className="sr-only">
          <SheetTitle>Sidebar</SheetTitle>
          <SheetDescription>Displays the mobile sidebar.</SheetDescription>
        </SheetHeader>
        {/* Only one content tree is mounted: no duplicate menus or queries. */}
        {openMobile && <Presentation expanded>{children}</Presentation>}
      </SheetContent>
    </Sheet>
  );
}
