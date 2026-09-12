"use client";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

export function WorkspaceMobileSidebarTrigger({
  className,
}: {
  className?: string;
}) {
  return <SidebarTrigger className={cn("md:hidden", className)} />;
}
