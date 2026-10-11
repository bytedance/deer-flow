"use client";

import { MenuIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

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

// Nextra's search results render in a portal outside the sheet, so a tap on a
// result would otherwise count as an outside click and close the sheet first.
const SEARCH_RESULTS_SELECTOR = ".nextra-search-results";

function isSearchResultsTarget(target: EventTarget | null) {
  return target instanceof Element && !!target.closest(SEARCH_RESULTS_SELECTOR);
}

export function MobileNav({
  links,
  search,
}: {
  links: MobileNavLink[];
  search?: ReactNode;
}) {
  const pathname = usePathname();
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
        side="right"
        className="w-64"
        onInteractOutside={(event) => {
          if (isSearchResultsTarget(event.target)) event.preventDefault();
        }}
      >
        <SheetHeader>
          <SheetTitle className="font-serif text-xl">DeerFlow</SheetTitle>
        </SheetHeader>
        {search && <div className="px-4 [&_input]:h-11">{search}</div>}
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
