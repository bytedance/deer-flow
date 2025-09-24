// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import SyntaxHighlighter from "react-syntax-highlighter";
import { docco, dark } from "react-syntax-highlighter/dist/esm/styles/hljs";

import { ToolBadge } from "~/components/deer-flow/tool-badge";
import { Tooltip } from "~/components/deer-flow/tooltip";
import { Card } from "~/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import { findMCPTool } from "~/core/mcp";
import { cn } from "~/lib/utils";

export interface ToolExecutionResult {
  toolName: string;
  serverName?: string;
  parameters: Record<string, unknown>;
  result: string;
  executionTime?: number;
  status: "success" | "error" | "partial";
}

interface ToolExecutionDetailsProps {
  execution: ToolExecutionResult;
  className?: string;
}

export function ToolExecutionDetails({
  execution,
  className,
}: ToolExecutionDetailsProps) {
  const { resolvedTheme } = useTheme();
  
  // Get tool details from MCP registry
  findMCPTool(execution.toolName);
  
  // Format execution time
  const formattedTime = execution.executionTime 
    ? `${(execution.executionTime / 1000).toFixed(2)}s`
    : "N/A";
  
  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="border-b p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ToolBadge 
              toolName={execution.toolName} 
              server={execution.serverName}
            />
            <span className={cn(
              "rounded-full px-2 py-0.5 text-xs",
              execution.status === "success" 
                ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
                : execution.status === "error"
                ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300"
                : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300"
            )}>
              {execution.status}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Tooltip title="Execution Time">
              <div className="flex items-center text-xs text-muted-foreground">
                <Info className="mr-1 h-3 w-3" />
                {formattedTime}
              </div>
            </Tooltip>
          </div>
        </div>
      </div>
      
      <Tabs defaultValue="result" className="w-full">
        <div className="border-b px-4">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="result">Result</TabsTrigger>
            <TabsTrigger value="parameters">Parameters</TabsTrigger>
          </TabsList>
        </div>
        
        <TabsContent value="result" className="p-4">
          <div className="max-h-[300px] overflow-y-auto rounded-md bg-muted p-2">
            <SyntaxHighlighter
              language="json"
              style={resolvedTheme === "dark" ? dark : docco}
              customStyle={{
                background: "transparent",
                border: "none",
                boxShadow: "none",
              }}
            >
              {execution.result}
            </SyntaxHighlighter>
          </div>
        </TabsContent>
        
        <TabsContent value="parameters" className="p-4">
          <div className="max-h-[300px] overflow-y-auto rounded-md bg-muted p-2">
            <SyntaxHighlighter
              language="json"
              style={resolvedTheme === "dark" ? dark : docco}
              customStyle={{
                background: "transparent",
                border: "none",
                boxShadow: "none",
              }}
            >
              {JSON.stringify(execution.parameters, null, 2)}
            </SyntaxHighlighter>
          </div>
        </TabsContent>
      </Tabs>
    </Card>
  );
}