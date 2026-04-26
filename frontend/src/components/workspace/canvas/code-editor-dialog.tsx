"use client";

import { useCallback, useState, useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { CanvasNode, NodeType } from "@/core/canvas/types";
import { cn } from "@/lib/utils";

// 变量定义
interface Variable {
  name: string;
  description?: string;
}

interface CodeEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  node: CanvasNode | null;
  nodeType: NodeType | null;
  code: string;
  onCodeChange: (code: string) => void;
  variables?: Variable[];
  className?: string;
}

// 获取编辑器标题
function getEditorTitle(nodeType: NodeType | null): string {
  switch (nodeType) {
    case "sql_executor":
      return "编辑 SQL 查询";
    case "python_script":
      return "编辑 Python 脚本";
    default:
      return "编辑代码";
  }
}

// 获取语言标识
function getLanguage(nodeType: NodeType | null): string {
  switch (nodeType) {
    case "sql_executor":
      return "sql";
    case "python_script":
      return "python";
    default:
      return "text";
  }
}

// 获取占位符
function getPlaceholder(nodeType: NodeType | null): string {
  switch (nodeType) {
    case "sql_executor":
      return "SELECT * FROM table_name WHERE id = {{variable_name}}";
    case "python_script":
      return "# 在这里编写 Python 代码\nimport pandas as pd\n\ndf = pd.read_csv('{{file_path}}')";
    default:
      return "输入代码...";
  }
}

export function CodeEditorDialog({
  open,
  onOpenChange,
  node,
  nodeType,
  code,
  onCodeChange,
  variables = [],
  className,
}: CodeEditorDialogProps) {
  const [localCode, setLocalCode] = useState(code);
  const [cursorPosition, setCursorPosition] = useState(0);
  const [showVariableInput, setShowVariableInput] = useState(false);
  const [newVariableName, setNewVariableName] = useState("");

  // 同步外部代码
  useEffect(() => {
    setLocalCode(code);
  }, [code]);

  // 插入变量
  const insertVariable = useCallback(
    (varName: string) => {
      const varSyntax = `{{${varName}}}`;
      const newCode =
        localCode.slice(0, cursorPosition) +
        varSyntax +
        localCode.slice(cursorPosition);
      setLocalCode(newCode);
      setCursorPosition(cursorPosition + varSyntax.length);
    },
    [localCode, cursorPosition],
  );

  // 添加新变量
  const handleAddVariable = useCallback(() => {
    if (newVariableName.trim()) {
      insertVariable(newVariableName.trim());
      setNewVariableName("");
      setShowVariableInput(false);
    }
  }, [newVariableName, insertVariable]);

  // 保存并关闭
  const handleSave = useCallback(() => {
    onCodeChange(localCode);
    onOpenChange(false);
  }, [localCode, onCodeChange, onOpenChange]);

  // 取消
  const handleCancel = useCallback(() => {
    setLocalCode(code);
    onOpenChange(false);
  }, [code, onOpenChange]);

  // 处理文本区域变化
  const handleTextareaChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setLocalCode(e.target.value);
    },
    [],
  );

  // 处理光标位置
  const handleTextareaSelect = useCallback(
    (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
      const target = e.currentTarget;
      setCursorPosition(target.selectionStart);
    },
    [],
  );

  const language = getLanguage(nodeType);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("max-w-3xl max-h-[80vh]", className)}>
        <DialogHeader>
          <DialogTitle>{getEditorTitle(nodeType)}</DialogTitle>
          <DialogDescription>
            {String(node?.data?.table_name ?? node?.data?.query_name ?? node?.data?.script_name ?? "编辑代码内容")}
            {language !== "text" && (
              <span className="ml-2 text-xs bg-muted px-1.5 py-0.5 rounded">
                {language.toUpperCase()}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {/* 代码编辑区域 */}
          <div className="relative">
            <textarea
              value={localCode}
              onChange={handleTextareaChange}
              onSelect={handleTextareaSelect}
              onClick={handleTextareaSelect}
              onKeyUp={handleTextareaSelect}
              placeholder={getPlaceholder(nodeType)}
              className={cn(
                "w-full min-h-[300px] p-4 rounded-md border bg-muted/30",
                "font-mono text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary",
                "placeholder:text-muted-foreground/50",
              )}
              spellCheck={false}
            />
          </div>

          {/* 变量面板 */}
          <div className="border rounded-md p-3">
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm">变量</Label>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowVariableInput(!showVariableInput)}
              >
                添加变量
              </Button>
            </div>

            {/* 添加变量输入框 */}
            {showVariableInput && (
              <div className="flex gap-2 mb-2">
                <Input
                  value={newVariableName}
                  onChange={(e) => setNewVariableName(e.target.value)}
                  placeholder="变量名称"
                  className="flex-1"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleAddVariable();
                    }
                  }}
                />
                <Button size="sm" onClick={handleAddVariable}>
                  插入
                </Button>
              </div>
            )}

            {/* 变量列表 */}
            <ScrollArea className="h-[80px]">
              <div className="flex flex-wrap gap-2">
                {variables.length > 0 ? (
                  variables.map((v) => (
                    <Button
                      key={v.name}
                      variant="secondary"
                      size="sm"
                      onClick={() => insertVariable(v.name)}
                      title={v.description}
                    >
                      {`{{${v.name}}}`}
                    </Button>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground">
                    暂无变量，点击"添加变量"创建
                  </span>
                )}
              </div>
            </ScrollArea>
          </div>

          {/* 语法提示 */}
          <div className="text-xs text-muted-foreground">
            <p>
              使用 <code className="bg-muted px-1 rounded">{"{{变量名}}"}</code> 语法插入变量。
              变量将在执行时被替换为实际值。
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCancel}>
            取消
          </Button>
          <Button onClick={handleSave}>保存</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
