"use client";

import { Database, Code, FileOutput, FileCode } from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { NodeType } from "@/core/canvas/types";
import { cn } from "@/lib/utils";

// 组件定义
interface ComponentItem {
  type: NodeType;
  name: string;
  description: string;
  icon: React.ReactNode;
  color: string;
}

const components: ComponentItem[] = [
  {
    type: "data_source",
    name: "Data Source",
    description: "从数据库或文件导入数据",
    icon: <Database className="h-5 w-5" />,
    color: "text-blue-500",
  },
  {
    type: "sql_executor",
    name: "SQL Executor",
    description: "执行 SQL 查询处理数据",
    icon: <FileCode className="h-5 w-5" />,
    color: "text-green-500",
  },
  {
    type: "python_script",
    name: "Python Script",
    description: "运行 Python 脚本处理数据",
    icon: <Code className="h-5 w-5" />,
    color: "text-yellow-500",
  },
  {
    type: "data_output",
    name: "Data Output",
    description: "导出数据到文件或数据库",
    icon: <FileOutput className="h-5 w-5" />,
    color: "text-purple-500",
  },
];

interface ComponentPanelProps {
  onDragStart?: (nodeType: NodeType) => void;
  onNodeAdd?: (nodeType: NodeType) => void;
  className?: string;
}

export function ComponentPanel({
  onDragStart,
  onNodeAdd,
  className,
}: ComponentPanelProps) {
  // 拖拽开始处理
  const handleDragStart = useCallback(
    (nodeType: NodeType) => {
      // 设置拖拽数据
      if (typeof window !== "undefined") {
        (window as unknown as { __canvasDragNodeType?: NodeType }).__canvasDragNodeType = nodeType;
      }
      onDragStart?.(nodeType);
    },
    [onDragStart],
  );

  // 双击添加节点
  const handleDoubleClick = useCallback(
    (nodeType: NodeType) => {
      onNodeAdd?.(nodeType);
    },
    [onNodeAdd],
  );

  return (
    <div className={cn("flex flex-col h-full", className)}>
      <div className="border-b p-3">
        <h3 className="text-sm font-medium">Components</h3>
        <p className="text-xs text-muted-foreground mt-1">
          拖拽到画布或双击添加
        </p>
      </div>
      <ScrollArea className="flex-1">
        <div className="grid gap-2 p-3">
          {components.map((component) => (
            <div
              key={component.type}
              draggable
              onDragStart={() => handleDragStart(component.type)}
              onDoubleClick={() => handleDoubleClick(component.type)}
              className={cn(
                "group flex items-start gap-3 rounded-md border bg-card p-3 cursor-grab",
                "hover:border-primary hover:bg-accent transition-colors",
                "active:cursor-grabbing",
              )}
            >
              <div
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted",
                  component.color,
                )}
              >
                {component.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{component.name}</div>
                <div className="text-xs text-muted-foreground line-clamp-2">
                  {component.description}
                </div>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
      <div className="border-t p-3">
        <Button variant="outline" size="sm" className="w-full">
          查看更多组件
        </Button>
      </div>
    </div>
  );
}

// 导出组件列表，供其他组件使用
export { components as componentList };
