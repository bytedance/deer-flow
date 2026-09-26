"use client";

import { MenuIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

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

export function MobileNav({ links }: { links: MobileNavLink[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild className="sm:hidden">
        <Button variant="ghost" size="icon" aria-label="Open menu">
          <MenuIcon className="size-5" />
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-64">
        <SheetHeader>
          <SheetTitle className="font-serif text-xl">DeerFlow</SheetTitle>
        </SheetHeader>
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
