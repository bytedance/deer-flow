import type { LucideIcon } from "lucide-react";
import { PlusIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceMobileSidebarTrigger } from "@/components/workspace/workspace-mobile-sidebar-trigger";
import { cn } from "@/lib/utils";

const headerActionClassName = "rounded-full px-5";

type WorkspaceGalleryHeaderActionProps = {
  label: string;
  href?: string;
  onClick?: () => void;
  icon?: LucideIcon;
};

export function WorkspaceGalleryHeaderAction({
  label,
  href,
  onClick,
  icon: Icon = PlusIcon,
}: WorkspaceGalleryHeaderActionProps) {
  const content = (
    <>
      <Icon className="size-4" />
      {label}
    </>
  );

  if (href) {
    return (
      <Button asChild className={headerActionClassName}>
        <Link href={href}>{content}</Link>
      </Button>
    );
  }

  return (
    <Button onClick={onClick} className={headerActionClassName}>
      {content}
    </Button>
  );
}

type WorkspaceGalleryHeaderProps = {
  icon: LucideIcon;
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

export function WorkspaceGalleryHeader({
  icon: Icon,
  title,
  subtitle,
  actions,
  className,
}: WorkspaceGalleryHeaderProps) {
  return (
    <header className={cn("mb-16 md:mb-20", className)}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <WorkspaceMobileSidebarTrigger className="mt-1 shrink-0" />
          <div className="max-w-4xl min-w-0 space-y-2">
            <h1 className="text-foreground flex items-center gap-3 text-3xl font-bold tracking-tight md:gap-3.5 md:text-4xl">
              <Icon className="size-8 shrink-0 md:size-9" aria-hidden />
              <span>{title}</span>
            </h1>
            {subtitle ? (
              <p className="text-muted-foreground text-sm leading-relaxed md:text-base">
                {subtitle}
              </p>
            ) : null}
          </div>
        </div>
        {actions ? (
          <div className="flex shrink-0 items-center self-end sm:self-auto">
            {actions}
          </div>
        ) : null}
      </div>
    </header>
  );
}
