"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { CanvasNode, SQLExecutorNodeData } from "@/core/canvas/types";
import { cn } from "@/lib/utils";

interface Variable {
  name: string;
  description?: string;
}

interface SQLExecutorEditorProps {
  node: CanvasNode;
  threadId: string;
  onUpdate: (data: Partial<SQLExecutorNodeData>) => void;
  onOpenCodeEditor: () => void;
  onValidate?: () => Promise<{ valid: boolean; errors: string[] } | undefined>;
  isValidating?: boolean;
  validationResult?: { valid: boolean; errors: string[] } | null;
}

/**
 * 从 SQL 查询中提取变量
 */
function extractVariables(sql: string): Variable[] {
  const regex = /\{\{([^}]+)\}\}/g;
  const variables: Variable[] = [];
  const seen = new Set<string>();

  // 使用 matchAll 方法代替 exec 循环，更安全
  const matches = sql.matchAll(regex);
  for (const match of matches) {
    const varName = match[1]?.trim();
    if (varName && !seen.has(varName)) {
      seen.add(varName);
      variables.push({ name: varName });
    }
  }

  return variables;
}

export function SQLExecutorEditor({
  node,
  threadId: _threadId,
  onUpdate,
  onOpenCodeEditor,
  onValidate,
  isValidating = false,
  validationResult = null,
}: SQLExecutorEditorProps) {
  const nodeData = node.data as SQLExecutorNodeData;

  // 本地状态
  const [localQueryName, setLocalQueryName] = useState(
    nodeData.query_name ?? ""
  );

  // 提取变量
  const variables = extractVariables(nodeData.sql_query ?? "");

  // 查询名称更新
  const handleQueryNameChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setLocalQueryName(e.target.value);
    },
    []
  );

  const handleQueryNameBlur = useCallback(() => {
    if (localQueryName !== nodeData.query_name) {
      onUpdate({ query_name: localQueryName || undefined });
    }
  }, [localQueryName, nodeData.query_name, onUpdate]);

  // SQL 编辑
  const handleEditSQL = useCallback(() => {
    onOpenCodeEditor();
  }, [onOpenCodeEditor]);

  // SQL 验证
  const handleValidate = useCallback(async () => {
    if (onValidate) {
      await onValidate();
    }
  }, [onValidate]);

  // 计算 SQL 预览
  const sqlPreview = nodeData.sql_query ?? "";
  const hasSQL = sqlPreview.trim().length > 0;

  return (
    <div className="flex flex-col gap-4">
      {/* 输出表名 */}
      <div className="space-y-2">
        <Label htmlFor="query-name">查询名称</Label>
        <Input
          id="query-name"
          value={localQueryName}
          onChange={handleQueryNameChange}
          onBlur={handleQueryNameBlur}
          placeholder="输入查询名称"
        />
        <p className="text-xs text-muted-foreground">
          查询名称用于标识和引用此 SQL 查询的结果
        </p>
      </div>

      {/* SQL 编辑按钮 */}
      <div className="space-y-2">
        <Label>SQL 查询</Label>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleEditSQL}
            className="flex-1"
          >
            {hasSQL ? "编辑 SQL" : "编写 SQL"}
          </Button>
          {onValidate && (
            <Button
              variant="outline"
              onClick={handleValidate}
              disabled={!hasSQL || isValidating}
            >
              {isValidating ? "验证中..." : "验证 SQL"}
            </Button>
          )}
        </div>
      </div>

      {/* SQL 预览 */}
      <div className="space-y-2">
        <Label>SQL 预览</Label>
        <ScrollArea className="h-24 border rounded-md bg-muted/30">
          <div className="p-3 font-mono text-sm whitespace-pre-wrap">
            {hasSQL ? sqlPreview : "暂无 SQL 查询"}
          </div>
        </ScrollArea>
      </div>

      {/* 验证结果 */}
      {validationResult && (
        <div
          className={cn(
            "flex items-start gap-2 p-3 rounded-md",
            validationResult.valid
              ? "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300"
              : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300"
          )}
        >
          {validationResult.valid ? (
            <CheckCircle2 className="h-5 w-5 mt-0.5" />
          ) : (
            <XCircle className="h-5 w-5 mt-0.5" />
          )}
          <div className="flex flex-col">
            <span className="font-medium">
              {validationResult.valid ? "SQL 有效" : "SQL 无效"}
            </span>
            {validationResult.errors.length > 0 && (
              <ul className="text-sm mt-1 list-disc list-inside">
                {validationResult.errors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* 变量列表 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>变量</Label>
          <span className="text-xs text-muted-foreground">
            使用 {"{{变量名}}"} 格式
          </span>
        </div>
        <ScrollArea className="h-20 border rounded-md">
          {variables.length > 0 ? (
            <div className="p-3 flex flex-wrap gap-2">
              {variables.map((var_) => (
                <span
                  key={var_.name}
                  className="inline-flex items-center px-2 py-1 rounded-md bg-secondary text-sm font-medium"
                >
                  {`{{${var_.name}}}`}
                </span>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
              暂无变量，在 SQL 中使用 {"{{变量名}}"} 格式添加
            </div>
          )}
        </ScrollArea>
      </div>

      {/* 提示 */}
      <div className="text-xs text-muted-foreground">
        <p>
          使用 <code className="bg-muted px-1 rounded">{"{{变量名}}"}</code>{" "}
          语法插入变量。
        </p>
        <p className="mt-1">变量将在执行时被替换为上游节点的输出数据。</p>
      </div>
    </div>
  );
}