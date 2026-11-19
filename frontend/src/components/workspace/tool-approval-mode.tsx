"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ShieldCheckIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  revokeThreadGrants,
  useToolApprovalFeature,
  type ApprovalMode,
} from "@/core/threads/tool-approvals";

export function ToolApprovalMode({
  value,
  onChange,
  threadId,
  disabled,
}: {
  value?: ApprovalMode;
  onChange: (mode: ApprovalMode) => void;
  threadId?: string;
  disabled?: boolean;
}) {
  const feature = useToolApprovalFeature();
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const [revoking, setRevoking] = useState(false);
  const copy = t.humanInput.approval;
  if (!feature.data?.enabled) return null;
  const mode = value ?? feature.data.default_mode;
  const labels = {
    ask: copy.modeAsk,
    auto: copy.modeAuto,
    full: copy.modeFull,
  };
  const descriptions = {
    ask: copy.askDescription,
    auto: copy.autoDescription,
    full: copy.fullDescription,
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          aria-label={copy.modeLabel}
          className="gap-1 px-2 text-xs"
        >
          <ShieldCheckIcon className="size-3" />
          {labels[mode]}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-80" align="start">
        <DropdownMenuLabel>{copy.modeLabel}</DropdownMenuLabel>
        {feature.data.allowed_modes.map((option) => (
          <DropdownMenuItem
            key={option}
            onSelect={() => onChange(option)}
            aria-selected={mode === option}
          >
            <div className="space-y-1">
              <div className={option === "full" ? "text-destructive" : ""}>
                {labels[option]}
                {mode === option ? " ✓" : ""}
              </div>
              <div className="text-muted-foreground text-xs">
                {descriptions[option]}
              </div>
            </div>
          </DropdownMenuItem>
        ))}
        {threadId ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              disabled={revoking}
              onSelect={() => {
                setRevoking(true);
                void revokeThreadGrants(threadId)
                  .then(async () => {
                    await queryClient.invalidateQueries({
                      queryKey: ["tool-approvals"],
                    });
                    toast.success(copy.grantsRevoked);
                  })
                  .catch((error: unknown) =>
                    toast.error(
                      error instanceof Error ? error.message : String(error),
                    ),
                  )
                  .finally(() => setRevoking(false));
              }}
            >
              {copy.revokeGrants}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
