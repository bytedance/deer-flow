"use client";

import type { PropsWithChildren } from "react";

import {
  Artifact,
  ArtifactContent,
  ArtifactDescription,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { cn } from "@/lib/utils";

type VsfxFloatingWindowProps = PropsWithChildren<{
  className?: string;
  contentClassName?: string;
  description?: string;
  "data-testid"?: string;
  title: string;
}>;

export function VsfxFloatingWindow({
  children,
  className,
  contentClassName,
  description,
  title,
  ...props
}: VsfxFloatingWindowProps) {
  return (
    <Artifact
      className={cn(
        "pointer-events-auto absolute top-4 right-4 z-20 flex h-[calc(100%-2rem)] max-h-[40rem] min-h-0 w-80 flex-col overflow-hidden border shadow-xl",
        className,
      )}
      {...props}
    >
      <ArtifactHeader className="px-3 py-2">
        <div className="min-w-0">
          <ArtifactTitle>{title}</ArtifactTitle>
          {description ? (
            <ArtifactDescription className="mt-1 text-xs">
              {description}
            </ArtifactDescription>
          ) : null}
        </div>
      </ArtifactHeader>
      <ArtifactContent className={cn("min-h-0 flex-1 p-0", contentClassName)}>
        {children}
      </ArtifactContent>
    </Artifact>
  );
}
