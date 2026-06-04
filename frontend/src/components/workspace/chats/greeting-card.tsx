"use client";

import { BotIcon } from "@/components/ui/icons";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface GreetingCardProps {
  greeting: string;
  suggestions: string[];
  isLoading?: boolean;
  onSuggestionClick?: (suggestion: string) => void;
  className?: string;
}

export function GreetingCard({
  greeting,
  suggestions,
  isLoading = false,
  onSuggestionClick,
  className,
}: GreetingCardProps) {
  if (isLoading) {
    return (
      <div className={cn("flex flex-col items-center gap-4 py-8", className)}>
        <Skeleton className="size-12 rounded-full" />
        <Skeleton className="h-5 w-64 rounded" />
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24 rounded-full" />
          <Skeleton className="h-9 w-28 rounded-full" />
          <Skeleton className="h-9 w-20 rounded-full" />
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col items-center gap-4 py-8", className)}>
      <div className="bg-primary/10 flex size-12 items-center justify-center rounded-full">
        <BotIcon className="text-primary size-6" />
      </div>
      <p className="text-foreground max-w-md text-center text-base leading-relaxed">
        {greeting}
      </p>
      {suggestions.length > 0 && (
        <div className="flex flex-wrap justify-center gap-2">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="border-border bg-background hover:bg-accent hover:text-accent-foreground rounded-lg border px-4 py-2 text-sm transition-colors"
              onClick={() => onSuggestionClick?.(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
