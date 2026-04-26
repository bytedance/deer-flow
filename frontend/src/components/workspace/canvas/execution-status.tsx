"use client";

import {
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  Play,
  Eye,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { CanvasStatus, ExecutionStatusResponse, NodeResult } from "@/core/canvas/types";
import { cn } from "@/lib/utils";

interface ExecutionStatusProps {
  status: ExecutionStatusResponse | null;
  nodeResults?: Record<string, NodeResult>;
  onNodeSelect?: (nodeId: string) => void;
  onNodePreview?: (nodeId: string) => void;
  isLoading?: boolean;
}

const statusIcons: Record<CanvasStatus, React.ReactNode> = {
  idle: <Clock className="h-4 w-4" />,
  running: <Loader2 className="h-4 w-4 animate-spin" />,
  paused: <Clock className="h-4 w-4" />,
  completed: <CheckCircle className="h-4 w-4 text-green-500" />,
  failed: <XCircle className="h-4 w-4 text-red-500" />,
};

// 节点执行状态图标
const nodeStatusIcons: Record<"pending" | "running" | "completed" | "failed", React.ReactNode> = {
  pending: <Clock className="h-3 w-3 text-gray-400" />,
  running: <Loader2 className="h-3 w-3 animate-spin text-yellow-500" />,
  completed: <CheckCircle className="h-3 w-3 text-green-500" />,
  failed: <XCircle className="h-3 w-3 text-red-500" />,
};

// 状态文本
const statusLabels: Record<CanvasStatus, string> = {
  idle: "空闲",
  running: "执行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
};

export function ExecutionStatus({
  status,
  nodeResults = {},
  onNodeSelect,
  onNodePreview,
  isLoading,
}: ExecutionStatusProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  if (!status && Object.keys(nodeResults).length === 0) return null;

  // 获取节点执行状态
  const getNodeStatus = (nodeId: string): "pending" | "running" | "completed" | "failed" => {
    if (status?.current_node === nodeId) return "running";
    if (status?.completed_nodes.includes(nodeId)) {
      const result = nodeResults[nodeId];
      return result?.success ? "completed" : "failed";
    }
    if (status?.pending_nodes.includes(nodeId)) return "pending";
    return "pending";
  };

  // 处理节点点击
  const handleNodeClick = (nodeId: string) => {
    setSelectedNodeId(selectedNodeId === nodeId ? null : nodeId);
    onNodeSelect?.(nodeId);
  };

  // 处理预览点击
  const handlePreviewClick = (nodeId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    onNodePreview?.(nodeId);
  };

  // 获取所有节点
  const allNodeIds = [
    ...new Set([
      ...(status?.completed_nodes ?? []),
      ...(status?.pending_nodes ?? []),
      ...(status?.current_node ? [status.current_node] : []),
      ...Object.keys(nodeResults),
    ]),
  ];

  const displayStatus = status?.status ?? "idle";

  return (
    <div className="rounded-md border bg-background shadow-sm max-w-sm">
      {/* 头部 - 总是显示 */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-accent/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {statusIcons[displayStatus]}
          <span className="text-sm font-medium">{statusLabels[displayStatus]}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {status?.completed_nodes.length ?? 0} / {allNodeIds.length} 节点
          </span>
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          )}
        </div>
      </button>

      {/* 展开内容 - 节点列表 */}
      {isExpanded && allNodeIds.length > 0 && (
        <ScrollArea className="max-h-64 border-t">
          <div className="p-2 space-y-1">
            {allNodeIds.map((nodeId) => {
              const nodeStatus = getNodeStatus(nodeId);
              const result = nodeResults[nodeId];
              const isSelected = selectedNodeId === nodeId;

              return (
                <div
                  key={nodeId}
                  onClick={() => handleNodeClick(nodeId)}
                  className={cn(
                    "flex items-center justify-between p-2 rounded-md cursor-pointer",
                    "hover:bg-accent transition-colors",
                    isSelected && "bg-accent"
                  )}
                >
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {nodeStatusIcons[nodeStatus]}
                    <span className="text-xs truncate flex-1">
                      {nodeId.replace(/^node-/, "")}
                    </span>
                  </div>

                  {/* 操作按钮 */}
                  {nodeStatus === "completed" && result?.success && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2"
                      onClick={(e) => handlePreviewClick(nodeId, e)}
                    >
                      <Eye className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </ScrollArea>
      )}

      {/* 选中节点的详情面板 */}
      {isExpanded && selectedNodeId && nodeResults[selectedNodeId] && (
        <div className="border-t p-3 bg-muted/30">
          <div className="text-xs font-medium mb-2">执行结果</div>
          <div className="space-y-1 text-xs text-muted-foreground">
            {nodeResults[selectedNodeId]?.output_table && (
              <div>输出表: {nodeResults[selectedNodeId]?.output_table}</div>
            )}
            {nodeResults[selectedNodeId]?.rows_affected !== undefined && (
              <div>影响行数: {nodeResults[selectedNodeId]?.rows_affected}</div>
            )}
            {nodeResults[selectedNodeId]?.error && (
              <div className="text-red-500">错误: {nodeResults[selectedNodeId]?.error}</div>
            )}
          </div>
        </div>
      )}

      {/* 执行中的进度条 */}
      {isLoading && (
        <div className="h-1 bg-muted overflow-hidden">
          <div className="h-full bg-primary animate-pulse w-full" />
        </div>
      )}
    </div>
  );
}
