// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { PencilRuler } from "lucide-react";
import { useTranslations } from "next-intl";

import { Tooltip } from "~/components/deer-flow/tooltip";
import { Badge } from "~/components/ui/badge";
import { cn } from "~/lib/utils";
import { findMCPTool } from "~/core/mcp";

interface ToolBadgeProps {
  toolName: string;
  server?: string;
  onClick?: () => void;
  className?: string;
}

export function ToolBadge({
  toolName,
  server,
  onClick,
  className,
}: ToolBadgeProps) {
  const t = useTranslations("chat.research");
  const tool = findMCPTool(toolName);
  
  // Format the display name by removing the mcp_ prefix
  const displayName = toolName.replace(/^mcp_/, "");
  
  return (
    <Tooltip title={tool?.description || toolName}>
      <Badge
        variant="outline"
        className={cn(
          "flex cursor-pointer items-center gap-1 px-2 py-1 hover:bg-primary/10",
          className
        )}
        onClick={onClick}
      >
        <PencilRuler className="h-3 w-3" />
        <span className="text-xs">{displayName}</span>
        {server && (
          <span className="text-muted-foreground rounded-full bg-muted px-1 text-[10px]">
            {server}
          </span>
        )}
      </Badge>
    </Tooltip>
  );
}