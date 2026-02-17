"use client";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { type LucideIcon, XIcon } from "lucide-react";
import type { ComponentProps, HTMLAttributes } from "react";

/** Props for the root artifact container. */
export type ArtifactProps = HTMLAttributes<HTMLDivElement>;

/** Root container for an artifact card with border and shadow styling. */
export const Artifact = ({ className, ...props }: ArtifactProps) => (
  <div
    className={cn(
      "bg-background flex flex-col overflow-hidden rounded-lg border shadow-lg",
      className,
    )}
    {...props}
  />
);

/** Props for the artifact header bar. */
export type ArtifactHeaderProps = HTMLAttributes<HTMLDivElement>;

/** Header bar displayed at the top of an artifact, containing title and actions. */
export const ArtifactHeader = ({
  className,
  ...props
}: ArtifactHeaderProps) => (
  <div
    className={cn(
      "bg-muted/50 flex items-center justify-between border-b px-4 py-3",
      className,
    )}
    {...props}
  />
);

/** Props for the artifact close button. */
export type ArtifactCloseProps = ComponentProps<typeof Button>;

/** Close button that dismisses the artifact panel. Renders an X icon by default. */
export const ArtifactClose = ({
  className,
  children,
  size = "sm",
  variant = "ghost",
  ...props
}: ArtifactCloseProps) => (
  <Button
    className={cn(
      "text-muted-foreground hover:text-foreground size-8 p-0",
      className,
    )}
    size={size}
    type="button"
    variant={variant}
    {...props}
  >
    {children ?? <XIcon className="size-4" />}
    <span className="sr-only">Close</span>
  </Button>
);

/** Props for the artifact title text. */
export type ArtifactTitleProps = HTMLAttributes<HTMLParagraphElement>;

/** Title label displayed in the artifact header. */
export const ArtifactTitle = ({ className, ...props }: ArtifactTitleProps) => (
  <div
    className={cn("text-foreground text-sm font-medium", className)}
    {...props}
  />
);

/** Props for the artifact description text. */
export type ArtifactDescriptionProps = HTMLAttributes<HTMLParagraphElement>;

/** Secondary description text displayed below the artifact title. */
export const ArtifactDescription = ({
  className,
  ...props
}: ArtifactDescriptionProps) => (
  <p className={cn("text-muted-foreground text-sm", className)} {...props} />
);

/** Props for the artifact action button group container. */
export type ArtifactActionsProps = HTMLAttributes<HTMLDivElement>;

/** Horizontal row of action buttons in the artifact header. */
export const ArtifactActions = ({
  className,
  ...props
}: ArtifactActionsProps) => (
  <div className={cn("flex items-center gap-1", className)} {...props} />
);

/** Props for an individual artifact action button. */
export type ArtifactActionProps = ComponentProps<typeof Button> & {
  /** Tooltip text shown on hover. */
  tooltip?: string;
  /** Accessible label for screen readers. Falls back to `tooltip` if omitted. */
  label?: string;
  /** Lucide icon component rendered inside the button. */
  icon?: LucideIcon;
};

/**
 * Icon button for artifact actions (copy, download, open, etc.).
 * Wraps itself in a tooltip when `tooltip` is provided.
 */
export const ArtifactAction = ({
  tooltip,
  label,
  icon: Icon,
  children,
  className,
  size = "sm",
  variant = "ghost",
  ...props
}: ArtifactActionProps) => {
  const button = (
    <Button
      className={cn(
        "text-muted-foreground hover:text-foreground size-8 p-0",
        className,
      )}
      size={size}
      type="button"
      variant={variant}
      {...props}
    >
      {Icon ? <Icon className="size-4" /> : children}
      <span className="sr-only">{label || tooltip}</span>
    </Button>
  );

  if (tooltip) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent>
            <p>{tooltip}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return button;
};

/** Props for the scrollable artifact body area. */
export type ArtifactContentProps = HTMLAttributes<HTMLDivElement>;

/** Scrollable content area that fills the remaining space of an artifact card. */
export const ArtifactContent = ({
  className,
  ...props
}: ArtifactContentProps) => (
  <div
    className={cn("min-h-0 flex-1 overflow-auto p-4", className)}
    {...props}
  />
);
