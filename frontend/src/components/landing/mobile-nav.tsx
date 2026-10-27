"use client";

import { Portal } from "@headlessui/react";
import { MenuIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

export type MobileNavLink = {
  href: string;
  label: string;
};

export function MobileNav({
  links,
  search,
}: {
  links: MobileNavLink[];
  search?: ReactNode;
}) {
  const pathname = usePathname();
  const contentRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  // Close on navigation (e.g. picking a search result). The docs layout keeps
  // this component mounted across pages, so reset during render rather than
  // only hiding the sheet while the path differs.
  const [openedPath, setOpenedPath] = useState(pathname);
  if (pathname !== openedPath) {
    setOpenedPath(pathname);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    // Same-page search results only change the hash.
    const close = () => setOpen(false);
    window.addEventListener("hashchange", close);
    return () => window.removeEventListener("hashchange", close);
  }, [open]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild className="sm:hidden">
        <Button variant="ghost" size="icon" aria-label="Open menu">
          <MenuIcon className="size-5" />
        </Button>
      </SheetTrigger>
      <SheetContent
        ref={contentRef}
        side="right"
        className="w-64"
        aria-describedby={undefined}
        onClick={(event) => {
          // A result at the current hash emits neither pathname nor hashchange.
          // Bubble after the result's own navigation handler has run.
          if (
            event.target instanceof Element &&
            event.target.closest(".nextra-search-results a[href]")
          ) {
            setOpen(false);
          }
        }}
        onKeyDownCapture={(event) => {
          if (event.key !== "Enter" || !(event.target instanceof Element))
            return;
          const activeId = event.target.getAttribute("aria-activedescendant");
          const option = activeId ? document.getElementById(activeId) : null;
          if (
            !option?.matches(".nextra-search-results a[href]") ||
            !contentRef.current?.contains(option)
          )
            return;
          // Headless UI stops Enter propagation. Let its selection handler run
          // first, and close only if it handled the key (not IME composition).
          const nativeEvent = event.nativeEvent;
          // A microtask can run between native capture and bubble listeners.
          window.setTimeout(() => {
            if (nativeEvent.defaultPrevented && !nativeEvent.isComposing) {
              setOpen(false);
            }
          }, 0);
        }}
      >
        <SheetHeader>
          <SheetTitle className="font-serif text-xl">DeerFlow</SheetTitle>
        </SheetHeader>
        {search && (
          // Radix's modal scroll lock only allows descendants of its content.
          <Portal.Group as="div" target={contentRef}>
            <div className="px-4 [&_input]:h-11">{search}</div>
          </Portal.Group>
        )}
        <nav className="flex flex-col gap-1 px-4 text-base font-medium">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setOpen(false)}
              className="text-secondary-foreground hover:text-foreground rounded-md py-2 transition-colors"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
