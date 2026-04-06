"use client";

import type { LucideIcon } from "lucide-react";
import { Children, type ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const STAGGER_DELAY_MS = 60;
const STAGGER_DELAY_MS_OFFSET = 250;

export type SuggestionsProps = ComponentProps<typeof ScrollArea>;

export const Suggestions = ({
  className,
  children,
  ...props
}: SuggestionsProps) => (
  <ScrollArea className="overflow-x-auto whitespace-normal" {...props}>
    <div
      className={cn("flex w-full flex-wrap items-center gap-2", className)}
      data-slot="suggestions-list"
    >
      {Children.map(children, (child, index) =>
        child != null ? (
          <span
            className="animate-fade-in-up max-w-full opacity-0"
            style={{
              animationDelay: `${STAGGER_DELAY_MS_OFFSET + index * STAGGER_DELAY_MS}ms`,
            }}
          >
            {child}
          </span>
        ) : (
          child
        ),
      )}
    </div>
    <ScrollBar className="hidden" orientation="horizontal" />
  </ScrollArea>
);

export type SuggestionProps = Omit<ComponentProps<typeof Button>, "onClick"> & {
  suggestion: React.ReactNode;
  icon?: LucideIcon;
  onClick?: () => void;
};

export const Suggestion = ({
  suggestion,
  onClick,
  className,
  icon: Icon,
  variant = "outline",
  size = "sm",
  children,
  ...props
}: SuggestionProps) => {
  const handleClick = () => {
    onClick?.();
  };

  return (
    <Button
      className={cn(
        "text-muted-foreground h-auto max-w-full cursor-pointer rounded-full px-4 py-2 text-center text-xs font-normal whitespace-normal",
        className,
      )}
      onClick={handleClick}
      size={size}
      type="button"
      variant={variant}
      {...props}
    >
      {Icon && <Icon className="size-4" />}
      {children ?? suggestion}
    </Button>
  );
};
