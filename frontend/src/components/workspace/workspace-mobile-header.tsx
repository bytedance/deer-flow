"use client";

import Link from "next/link";
import { Menu, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import { env } from "@/env";

export function WorkspaceMobileHeader() {
  const { openMobile, setOpenMobile } = useSidebar();

  return (
    <div className="sticky top-0 z-50 flex md:hidden h-12 shrink-0 items-center gap-2 border-b bg-background px-4">
      <Button
        variant="ghost"
        size="icon"
        className="size-7 opacity-50 hover:opacity-100"
        onClick={() => setOpenMobile(!openMobile)}
        aria-label={openMobile ? "Close sidebar" : "Open sidebar"}
      >
        {openMobile ? (
          <X className="size-4" />
        ) : (
          <Menu className="size-4" />
        )}
      </Button>
      {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
        <Link href="/" className="font-serif text-primary">
          DeerFlow
        </Link>
      ) : (
        <span className="font-serif text-primary">DeerFlow</span>
      )}
    </div>
  );
}
