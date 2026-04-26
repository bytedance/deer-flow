"use client";

import { Play, Square, Save, Trash2, Edit, Eye, Loader2, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Toggle } from "@/components/ui/toggle";
import type { CanvasStatus } from "@/core/canvas/types";
import { cn } from "@/lib/utils";

import { useCanvasContext } from "./context";

interface CanvasToolbarProps {
  onExecute?: () => void;
  onStop?: () => void;
  onSave?: () => void;
  onDelete?: () => void;
  isExecuting?: boolean;
  isSaving?: boolean;
  lastSaved?: Date | null;
}

// 状态指示器颜色
const statusColors: Record<CanvasStatus, string> = {
  idle: "bg-gray-400",
  running: "bg-yellow-500 animate-pulse",
  paused: "bg-orange-500",
  completed: "bg-green-500",
  failed: "bg-red-500",
};

// 状态文本
const statusLabels: Record<CanvasStatus, string> = {
  idle: "空闲",
  running: "执行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
};

export function CanvasToolbar({ onExecute, onStop, onSave, onDelete, isExecuting, isSaving, lastSaved }: CanvasToolbarProps) {
  const { canvas, canvasMode, setCanvasMode, executionStatus } = useCanvasContext();

  const status = executionStatus?.status ?? canvas?.status ?? "idle";

  return (
    <div className="flex items-center gap-2 rounded-md border bg-background px-3 py-2 shadow-sm">
      {/* Canvas 名称 */}
      <span className="text-sm font-medium">{canvas?.name ?? "Canvas"}</span>

      {/* 状态指示器 */}
      <div className="flex items-center gap-1.5">
        <div className={cn("h-2 w-2 rounded-full", statusColors[status])} />
        <span className="text-xs text-muted-foreground">{statusLabels[status]}</span>
      </div>

      <Separator orientation="vertical" className="h-6" />

      {/* 模式切换 */}
      <div className="flex items-center gap-1">
        <Toggle
          pressed={canvasMode === "edit"}
          onPressedChange={() => setCanvasMode("edit")}
          size="sm"
          aria-label="编辑模式"
          className={cn(
            "h-8 px-2",
            canvasMode === "edit" && "bg-primary text-primary-foreground"
          )}
        >
          <Edit className="h-4 w-4" />
        </Toggle>
        <Toggle
          pressed={canvasMode === "run"}
          onPressedChange={() => setCanvasMode("run")}
          size="sm"
          aria-label="运行模式"
          className={cn(
            "h-8 px-2",
            canvasMode === "run" && "bg-primary text-primary-foreground"
          )}
        >
          <Eye className="h-4 w-4" />
        </Toggle>
      </div>

      <Separator orientation="vertical" className="h-6" />

      {/* 执行控制 */}
      {canvasMode === "run" && (
        <>
          {isExecuting || status === "running" ? (
            <Button
              variant="outline"
              size="sm"
              onClick={onStop}
              className="text-red-600 hover:text-red-700"
            >
              <Square className="mr-1 h-4 w-4" />
              停止
            </Button>
          ) : (
            <Button
              variant="default"
              size="sm"
              onClick={onExecute}
              disabled={!canvas || canvas.nodes.length === 0}
            >
              {isExecuting ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-1 h-4 w-4" />
              )}
              执行
            </Button>
          )}
        </>
      )}

      {/* 保存按钮 */}
      <Button variant="outline" size="sm" onClick={onSave} disabled={isSaving}>
        {isSaving ? (
          <Loader2 className="mr-1 h-4 w-4 animate-spin" />
        ) : lastSaved ? (
          <Check className="mr-1 h-4 w-4 text-green-500" />
        ) : (
          <Save className="mr-1 h-4 w-4" />
        )}
        {isSaving ? "保存中" : "保存"}
      </Button>

      {/* 删除按钮（仅在编辑模式可用） */}
      {canvasMode === "edit" && (
        <>
          <Separator orientation="vertical" className="h-6" />
          <Button variant="ghost" size="sm" onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </>
      )}
    </div>
  );
}
