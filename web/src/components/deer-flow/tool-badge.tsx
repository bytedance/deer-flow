// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { PencilRuler } from "lucide-react";

import { Tooltip } from "~/components/deer-flow/tooltip";
import { Badge } from "~/components/ui/badge";
import { cn } from "~/lib/utils";
import { findMCPTool } from "~/core/mcp";

interface ToolBadgeProps {
  toolName: string;
  server?: string;
  onClick?: () => void;
  className?: string;
  size?: "sm" | "default";
}

export function ToolBadge({
  toolName,
  server,
  onClick,
  className,
  size = "default",
}: ToolBadgeProps) {
  const tool = findMCPTool(toolName);
  
  // Format the display name by removing the mcp_ prefix
  const displayName = toolName.replace(/^mcp_/, "");
  
  return (
    <Tooltip title={tool?.description || toolName}>
      <Badge
        variant="outline"
        className={cn(
          "flex items-center gap-1 px-2 py-1",
          onClick && "cursor-pointer hover:bg-primary/10",
          size === "sm" && "text-xs",
          className
        )}
        onClick={onClick}
      >
        <PencilRuler className={cn("h-3 w-3", size === "sm" && "h-2.5 w-2.5")} />
        <span className={cn("text-xs", size === "sm" && "text-[10px]")}>{displayName}</span>
        {server && (
          <span className={cn(
            "text-muted-foreground rounded-full bg-muted px-1 text-[10px]",
            size === "sm" && "text-[8px]"
          )}>
            {server}
          </span>
        )}
      </Badge>
    </Tooltip>
  );
}