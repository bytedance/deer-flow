import { BotIcon } from "@/components/ui/icons";

import { cn } from "@/lib/utils";

export function AssistantAvatar({
  icon,
  displayName,
  className,
}: {
  icon?: string | null;
  displayName?: string | null;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="bg-primary/10 flex size-7 shrink-0 items-center justify-center rounded-full">
        {icon ? (
          <span className="text-sm leading-none">{icon}</span>
        ) : (
          <BotIcon className="text-primary size-4" />
        )}
      </div>
      {displayName ? (
        <span className="text-muted-foreground text-sm font-medium">
          {displayName}
        </span>
      ) : null}
    </div>
  );
}
