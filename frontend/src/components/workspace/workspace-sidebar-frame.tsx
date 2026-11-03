"use client";

import { usePathname } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";

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
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <ExpandedContext.Provider value={expanded}>
      <div
        className="contents"
        onClickCapture={(event) => {
          if (
            !isMobile ||
            event.defaultPrevented ||
            !(event.target instanceof Element) ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
          )
            return;
          const link = event.target.closest<HTMLAnchorElement>("a[href]");
          if (
            !link ||
            link.hasAttribute("download") ||
            (link.target && link.target !== "_self")
          )
            return;
          const destination = new URL(link.href, window.location.href);
          if (
            destination.origin === window.location.origin &&
            destination.pathname !== window.location.pathname
          ) {
            // Release the focus trap before the destination mounts its input.
            setOpenMobile(false);
          }
        }}
      >
        {children}
      </div>
    </ExpandedContext.Provider>
  );
}

function RestoreSidebarFocus({
  railRef,
  pathnameRef,
}: {
  railRef: RefObject<HTMLDivElement | null>;
  pathnameRef: RefObject<string | null>;
}) {
  useLayoutEffect(() => {
    // Capture the opener before the drawer's focus scope moves focus inside.
    const opener = document.activeElement;
    const openedOn = pathnameRef.current;
    const restoreFocus = () => {
      if (
        pathnameRef.current !== openedOn ||
        document.activeElement !== document.body
      ) {
        return;
      }
      const target =
        opener instanceof HTMLElement &&
        opener !== document.body &&
        opener.isConnected
          ? opener
          : railRef.current?.querySelector<HTMLButtonElement>(
              '[data-sidebar="trigger"]',
            );
      target?.focus();
    };
    // Read the latest refs after the stock drawer portal has unmounted.
    return () => {
      setTimeout(restoreFocus, 0);
    };
  }, [railRef, pathnameRef]);
  return null;
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
  const pathname = usePathname();
  const pathnameRef = useRef(pathname);
  const railRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    pathnameRef.current = pathname;
    setOpenMobile(false);
  }, [pathname, setOpenMobile]);

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
        {isMobile && collapsible !== "none" && (
          <RestoreSidebarFocus railRef={railRef} pathnameRef={pathnameRef} />
        )}
        <Presentation
          expanded={isMobile && collapsible !== "none" ? openMobile : undefined}
        >
          {children}
        </Presentation>
      </Sidebar>
    );
  }

  return (
    <>
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
      <Sidebar side={side} variant={variant} collapsible={collapsible}>
        <RestoreSidebarFocus railRef={railRef} pathnameRef={pathnameRef} />
        {/* Only one content tree is mounted: no duplicate menus or queries. */}
        {openMobile && <Presentation expanded>{children}</Presentation>}
      </Sidebar>
    </>
  );
}
