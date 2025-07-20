// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useTranslations } from "next-intl";
import { useState } from "react";
import { Star, StarHalf, Info, Check, X, ThumbsUp, ThumbsDown } from "lucide-react";
import SyntaxHighlighter from "react-syntax-highlighter";
import { docco, dark } from "react-syntax-highlighter/dist/esm/styles/hljs";
import { useTheme } from "next-themes";

import { ToolBadge } from "~/components/deer-flow/tool-badge";
import { Tooltip } from "~/components/deer-flow/tooltip";
import { Button } from "~/components/ui/button";
import { Card } from "~/components/ui/card";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "~/components/ui/accordion";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import { findMCPTool } from "~/core/mcp";
import { cn } from "~/lib/utils";

export interface ToolExecutionResult {
  toolName: string;
  serverName?: string;
  parameters: Record<string, any>;
  result: string;
  executionTime?: number;
  status: "success" | "error" | "partial";
  contribution?: string;
}

interface ToolExecutionDetailsProps {
  execution: ToolExecutionResult;
  className?: string;
  onRateEffectiveness?: (rating: number) => void;
}

export function ToolExecutionDetails({
  execution,
  className,
  onRateEffectiveness,
}: ToolExecutionDetailsProps) {
  const t = useTranslations("chat.research");
  const { resolvedTheme } = useTheme();
  const [rating, setRating] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<string>("result");
  
  // Get tool details from MCP registry
  const tool = findMCPTool(execution.toolName);
  
  // Format execution time
  const formattedTime = execution.executionTime 
    ? `${(execution.executionTime / 1000).toFixed(2)}s`
    : t("notAvailable");
  
  // Handle rating click
  const handleRating = (value: number) => {
    setRating(value);
    if (onRateEffectiveness) {
      onRateEffectiveness(value);
    }
  };
  
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
              {execution.status === "success" ? t("success") : 
               execution.status === "error" ? t("error") : t("partial")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Tooltip title={t("executionTime")}>
              <div className="flex items-center text-xs text-muted-foreground">
                <Info className="mr-1 h-3 w-3" />
                {formattedTime}
              </div>
            </Tooltip>
          </div>
        </div>
      </div>
      
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <div className="border-b px-4">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="result">{t("result")}</TabsTrigger>
            <TabsTrigger value="parameters">{t("parameters")}</TabsTrigger>
            <TabsTrigger value="contribution">{t("contribution")}</TabsTrigger>
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
        
        <TabsContent value="contribution" className="p-4">
          {execution.contribution ? (
            <div className="space-y-4">
              <div className="rounded-md bg-muted p-3">
                <p className="text-sm">{execution.contribution}</p>
              </div>
              
              <div className="flex flex-col items-center gap-2">
                <p className="text-sm font-medium">{t("rateToolEffectiveness")}</p>
                <div className="flex items-center gap-2">
                  {[1, 2, 3, 4, 5].map((value) => (
                    <Button
                      key={value}
                      variant={rating === value ? "default" : "outline"}
                      size="sm"
                      className="h-8 w-8 p-0"
                      onClick={() => handleRating(value)}
                    >
                      {value <= (rating || 0) ? (
                        <Star className="h-4 w-4" />
                      ) : (
                        <Star className="h-4 w-4 text-muted-foreground opacity-50" />
                      )}
                    </Button>
                  ))}
                </div>
                {rating && (
                  <div className="mt-2 flex items-center gap-2">
                    <Button 
                      variant="ghost" 
                      size="sm"
                      className="h-8 text-xs"
                      onClick={() => setRating(null)}
                    >
                      {t("clearRating")}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground">
              <Info className="mb-2 h-8 w-8 opacity-50" />
              <p>{t("noContributionInfo")}</p>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </Card>
  );
}

interface ToolContributionMarkerProps {
  toolName: string;
  serverName?: string;
  contribution: string;
  className?: string;
  onClick?: () => void;
}

export function ToolContributionMarker({
  toolName,
  serverName,
  contribution,
  className,
  onClick,
}: ToolContributionMarkerProps) {
  const t = useTranslations("chat.research");
  
  return (
    <div 
      className={cn(
        "my-2 border-l-4 border-primary bg-primary/5 pl-3 pr-2 py-1",
        className,
        onClick && "cursor-pointer hover:bg-primary/10"
      )}
      onClick={onClick}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ToolBadge 
            toolName={toolName} 
            server={serverName}
            size="sm"
          />
          <span className="text-xs text-muted-foreground">{t("toolContribution")}</span>
        </div>
        {onClick && (
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
            <Info className="h-3 w-3" />
          </Button>
        )}
      </div>
      <div className="mt-1 text-sm">{contribution}</div>
    </div>
  );
}

interface ToolEffectivenessRatingProps {
  toolName: string;
  serverName?: string;
  rating: number;
  className?: string;
}

export function ToolEffectivenessRating({
  toolName,
  serverName,
  rating,
  className,
}: ToolEffectivenessRatingProps) {
  const t = useTranslations("chat.research");
  
  // Get rating text based on rating value
  const getRatingText = (rating: number): string => {
    if (rating >= 4.5) return t("excellent");
    if (rating >= 3.5) return t("good");
    if (rating >= 2.5) return t("average");
    if (rating >= 1.5) return t("fair");
    return t("poor");
  };
  
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <ToolBadge 
        toolName={toolName} 
        server={serverName}
        size="sm"
      />
      <div className="flex items-center">
        {[1, 2, 3, 4, 5].map((value) => {
          const isHalf = rating > value - 1 && rating < value;
          const isFull = rating >= value;
          
          return (
            <div key={value} className="text-yellow-500">
              {isFull ? (
                <Star className="h-3 w-3 fill-current" />
              ) : isHalf ? (
                <StarHalf className="h-3 w-3 fill-current" />
              ) : (
                <Star className="h-3 w-3 text-muted-foreground opacity-30" />
              )}
            </div>
          );
        })}
      </div>
      <span className="text-xs text-muted-foreground">
        {getRatingText(rating)}
      </span>
    </div>
  );
}

interface ToolExecutionSummaryProps {
  executions: ToolExecutionResult[];
  className?: string;
}

export function ToolExecutionSummary({
  executions,
  className,
}: ToolExecutionSummaryProps) {
  const t = useTranslations("chat.research");
  
  // Calculate statistics
  const totalTools = executions.length;
  const successfulTools = executions.filter(e => e.status === "success").length;
  const errorTools = executions.filter(e => e.status === "error").length;
  const partialTools = executions.filter(e => e.status === "partial").length;
  
  // Calculate average execution time
  const avgExecutionTime = executions
    .filter(e => e.executionTime !== undefined)
    .reduce((sum, e) => sum + (e.executionTime || 0), 0) / 
    executions.filter(e => e.executionTime !== undefined).length / 1000;
  
  return (
    <Card className={cn("p-4", className)}>
      <h3 className="mb-3 text-lg font-medium">{t("toolExecutionSummary")}</h3>
      
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-md bg-muted p-3 text-center">
          <div className="text-2xl font-bold">{totalTools}</div>
          <div className="text-xs text-muted-foreground">{t("totalTools")}</div>
        </div>
        
        <div className="rounded-md bg-green-100 dark:bg-green-900 p-3 text-center">
          <div className="text-2xl font-bold text-green-700 dark:text-green-300">
            {successfulTools}
          </div>
          <div className="text-xs text-green-600 dark:text-green-400">{t("successful")}</div>
        </div>
        
        <div className="rounded-md bg-red-100 dark:bg-red-900 p-3 text-center">
          <div className="text-2xl font-bold text-red-700 dark:text-red-300">
            {errorTools}
          </div>
          <div className="text-xs text-red-600 dark:text-red-400">{t("errors")}</div>
        </div>
        
        <div className="rounded-md bg-yellow-100 dark:bg-yellow-900 p-3 text-center">
          <div className="text-2xl font-bold text-yellow-700 dark:text-yellow-300">
            {partialTools}
          </div>
          <div className="text-xs text-yellow-600 dark:text-yellow-400">{t("partial")}</div>
        </div>
      </div>
      
      <div className="mt-4">
        <h4 className="mb-2 text-sm font-medium">{t("executionDetails")}</h4>
        <div className="rounded-md bg-muted p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm">{t("averageExecutionTime")}</span>
            <span className="font-medium">
              {isNaN(avgExecutionTime) ? t("notAvailable") : `${avgExecutionTime.toFixed(2)}s`}
            </span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-sm">{t("successRate")}</span>
            <span className="font-medium">
              {totalTools > 0 ? `${Math.round((successfulTools / totalTools) * 100)}%` : "0%"}
            </span>
          </div>
        </div>
      </div>
      
      <Accordion type="single" collapsible className="mt-4">
        <AccordionItem value="tools">
          <AccordionTrigger className="text-sm font-medium">
            {t("toolDetails")}
          </AccordionTrigger>
          <AccordionContent>
            <div className="space-y-2">
              {executions.map((execution, index) => (
                <div 
                  key={index}
                  className="flex items-center justify-between rounded-md bg-muted p-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <ToolBadge 
                      toolName={execution.toolName} 
                      server={execution.serverName}
                      size="sm"
                    />
                    {execution.status === "success" ? (
                      <Check className="h-4 w-4 text-green-500" />
                    ) : execution.status === "error" ? (
                      <X className="h-4 w-4 text-red-500" />
                    ) : (
                      <StarHalf className="h-4 w-4 text-yellow-500" />
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {execution.executionTime 
                      ? `${(execution.executionTime / 1000).toFixed(2)}s` 
                      : t("notAvailable")}
                  </div>
                </div>
              ))}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </Card>
  );
}