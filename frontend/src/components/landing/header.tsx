import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { Locale } from "@/core/i18n/locale";
import { cn } from "@/lib/utils";

export type HeaderProps = {
  className?: string;
  homeURL?: string;
  locale?: Locale;
};

export async function Header({ className, homeURL }: HeaderProps) {
  return (
    <header
      className={cn(
        "container-md fixed top-0 right-0 left-0 z-20 mx-auto flex h-16 items-center justify-between backdrop-blur-xs",
        className,
      )}
    >
      <div className="flex items-center gap-6">
        <Link href={homeURL ?? "/"}>
          <h1 className="text-xl font-semibold tracking-tight">EHM AI 工作台</h1>
        </Link>
      </div>
      <div className="ml-auto">
        <Button size="sm" asChild>
          <Link href="/workspace">进入工作台</Link>
        </Button>
      </div>
      <hr className="from-border/0 via-border/70 to-border/0 absolute top-16 right-0 left-0 z-10 m-0 h-px w-full border-none bg-linear-to-r" />
    </header>
  );
}
