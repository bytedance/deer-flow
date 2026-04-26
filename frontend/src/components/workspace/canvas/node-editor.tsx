"use client";

import { X } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useUpdateCanvas, useValidateSQL } from "@/core/canvas/hooks";
import type { CanvasNode, NodeType } from "@/core/canvas/types";

import { CodeEditorDialog } from "./code-editor-dialog";
import { useCanvasContext } from "./context";
import { DataPreviewDialog } from "./data-preview-dialog";
import { DataSourceEditor, SQLExecutorEditor } from "./editors";

// 节点类型显示名称
const NODE_TYPE_LABELS: Record<NodeType, string> = {
  data_source: "数据源",
  sql_executor: "SQL 执行器",
  python_script: "Python 脚本",
  data_output: "数据输出",
};

// 变量定义
interface Variable {
  name: string;
  description?: string;
}

/**
 * 从上游节点获取可用变量
 * 基于 DAG 的边关系提取上游节点的输出变量
 */
function getAvailableVariables(
  node: CanvasNode,
  canvasNodes: CanvasNode[],
  canvasEdges?: Array<{ source: string; target: string }>
): Variable[] {
  const variables: Variable[] = [];

  // 如果有边信息，基于边关系获取上游节点
  if (canvasEdges && canvasEdges.length > 0) {
    // 找到指向当前节点的所有边
    const upstreamNodeIds = canvasEdges
      .filter((edge) => edge.target === node.id)
      .map((edge) => edge.source);

    // 获取上游节点信息
    for (const nodeId of upstreamNodeIds) {
      const upstreamNode = canvasNodes.find((n) => n.id === nodeId);
      if (upstreamNode) {
        const nodeData = upstreamNode.data as Record<string, unknown>;
        const outputTable = typeof nodeData?.output_table === "string"
          ? nodeData.output_table
          : undefined;
        const displayName = (typeof nodeData?.display_name === "string"
          ? nodeData.display_name
          : null) ?? outputTable ?? String(upstreamNode.type);

        variables.push({
          name: `{{${nodeId}.output_table}}`,
          description: `${displayName} 的输出表`,
        });
      }
    }
  } else {
    // 如果没有边信息，返回所有其他节点的输出变量
    for (const otherNode of canvasNodes) {
      if (otherNode.id !== node.id) {
        const nodeData = otherNode.data as Record<string, unknown>;
        // 只有有输出表的节点才添加变量
        const outputTable = nodeData?.output_table;
        if (outputTable && typeof outputTable === "string") {
          const displayName = (typeof nodeData?.display_name === "string"
            ? nodeData.display_name
            : null) ?? outputTable ?? String(otherNode.type);

          variables.push({
            name: `{{${otherNode.id}.output_table}}`,
            description: `${displayName} 的输出表`,
          });
        } else if (nodeData?.table_name && typeof nodeData.table_name === "string") {
          // Data Source 节点使用 table_name
          const tableName = nodeData.table_name;
          variables.push({
            name: `{{${otherNode.id}.table_name}}`,
            description: `${tableName} 数据源`,
          });
        }
      }
    }
  }

  return variables;
}

export function NodeEditor() {
  const {
    selectedNodeId,
    canvas,
    setIsEditing,
    setCodeEditorOpen,
    setDataPreviewOpen,
    setDataPreviewNode,
    setCanvas,
  } = useCanvasContext();

  const selectedNode = canvas?.nodes.find((n) => n.id === selectedNodeId);

  // 获取 canvas 更新 hook
  const { updateCanvas, isUpdating } = useUpdateCanvas(canvas?.thread_id ?? "");

  // 验证状态
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
  } | null>(null);

  // SQL 验证 hook
  const { validateSQL, isValidating } = useValidateSQL(
    canvas?.thread_id ?? ""
  );

  // 获取节点类型
  const nodeType = selectedNode?.type;

  // 关闭编辑器
  const handleClose = useCallback(() => {
    setIsEditing(false);
  }, [setIsEditing]);

  // 打开代码编辑器
  const handleOpenCodeEditor = useCallback(() => {
    setCodeEditorOpen(true);
  }, [setCodeEditorOpen]);

  // 数据更新处理 - 实际保存到 canvas
  const handleDataUpdate = useCallback(
    (data: Record<string, unknown>) => {
      if (!canvas || !selectedNodeId || !selectedNode) return;

      // 更新本地 canvas 状态
      const updatedNodes = canvas.nodes.map((n) =>
        n.id === selectedNodeId
          ? { ...n, data: { ...n.data, ...data } }
          : n
      );

      const updatedCanvas = {
        ...canvas,
        nodes: updatedNodes,
      };

      // 更新本地状态
      setCanvas(updatedCanvas);

      // 保存到后端
      updateCanvas({
        nodes: updatedNodes,
      });
    },
    [canvas, selectedNodeId, selectedNode, setCanvas, updateCanvas]
  );

  // SQL 验证
  const handleValidateSQL = useCallback(async () => {
    if (!selectedNode || nodeType !== "sql_executor") return;

    const sql = (selectedNode.data as Record<string, unknown>)?.sql_query as
      | string
      | undefined;
    if (!sql) return;

    try {
      const result = await validateSQL({ sql });
      setValidationResult({
        valid: result.valid,
        errors: result.errors,
      });
      return {
        valid: result.valid,
        errors: result.errors,
      };
    } catch (error) {
      setValidationResult({
        valid: false,
        errors: [
          error instanceof Error ? error.message : "验证失败",
        ],
      });
      return {
        valid: false,
        errors: [error instanceof Error ? error.message : "验证失败"],
      };
    }
  }, [selectedNode, nodeType, validateSQL]);

  // 数据预览
  const handlePreviewData = useCallback(() => {
    if (selectedNodeId) {
      setDataPreviewNode(selectedNodeId);
      setDataPreviewOpen(true);
    }
  }, [selectedNodeId, setDataPreviewNode, setDataPreviewOpen]);

  // 获取可用变量
  const variables = selectedNode && canvas?.nodes
    ? getAvailableVariables(selectedNode, canvas.nodes, canvas?.edges)
    : [];

  // 渲染类型特定编辑器
  const renderTypeEditor = () => {
    if (!selectedNode || !nodeType) return null;

    switch (nodeType) {
      case "data_source":
        return (
          <DataSourceEditor
            node={selectedNode}
            onUpdate={handleDataUpdate}
            onPreview={handlePreviewData}
          />
        );

      case "sql_executor":
        return (
          <SQLExecutorEditor
            node={selectedNode}
            threadId={canvas?.thread_id ?? ""}
            onUpdate={handleDataUpdate}
            onOpenCodeEditor={handleOpenCodeEditor}
            onValidate={handleValidateSQL}
            isValidating={isValidating}
            validationResult={validationResult}
          />
        );

      case "python_script":
        return (
          <div className="space-y-4">
            <Button
              variant="outline"
              onClick={handleOpenCodeEditor}
              className="w-full"
            >
              编辑 Python 脚本
            </Button>
            {/* Python 脚本编辑器可以在这里添加更多配置 */}
          </div>
        );

      case "data_output":
        return (
          <div className="space-y-4">
            <Label>数据输出配置</Label>
            <p className="text-sm text-muted-foreground">
              数据输出节点将上游节点的结果导出为文件。
            </p>
            {/* 数据输出编辑器可以在这里添加更多配置 */}
          </div>
        );

      default:
        return (
          <div className="text-muted-foreground">
            未知的节点类型: {nodeType}
          </div>
        );
    }
  };

  if (!selectedNode) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        选择一个节点以编辑
      </div>
    );
  }

  // 获取节点显示名称
  const getNodeDisplayName = (): string => {
    const data = selectedNode.data as Record<string, unknown>;
    if (typeof data?.table_name === "string") return data.table_name;
    if (typeof data?.query_name === "string") return data.query_name;
    if (typeof data?.script_name === "string") return data.script_name;
    return "未选择";
  };

  return (
    <div className="h-full overflow-hidden flex flex-col">
      {/* 标题栏 */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex flex-col">
          <h3 className="font-medium flex items-center gap-2">
            {NODE_TYPE_LABELS[nodeType ?? "data_source"]}
            {isUpdating && (
              <span className="text-xs text-muted-foreground animate-pulse">
                保存中...
              </span>
            )}
          </h3>
          <p className="text-xs text-muted-foreground">
            ID: {selectedNode.id}
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={handleClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* 编辑内容 */}
      <ScrollArea className="flex-1 p-4">
        <div className="space-y-6">{renderTypeEditor()}</div>
      </ScrollArea>

      {/* 代码编辑器弹窗 */}
      <CodeEditorDialog
        open={false} // 通过 context 控制
        onOpenChange={setCodeEditorOpen}
        node={selectedNode}
        nodeType={nodeType ?? null}
        code={
          nodeType === "sql_executor"
            ? ((selectedNode.data as Record<string, unknown>)?.sql_query as string) ?? ""
            : nodeType === "python_script"
              ? ((selectedNode.data as Record<string, unknown>)?.code as string) ?? ""
              : ""
        }
        onCodeChange={(code) => {
          if (nodeType === "sql_executor") {
            handleDataUpdate({ sql_query: code });
          } else if (nodeType === "python_script") {
            handleDataUpdate({ code });
          }
        }}
        variables={variables}
      />

      {/* 数据预览弹窗 */}
      <DataPreviewDialog
        open={false} // 通过 context 控制
        onOpenChange={setDataPreviewOpen}
        data={null} // 需要通过 API 获取
        title="数据预览"
        description={
          nodeType === "data_source"
            ? `表: ${getNodeDisplayName()}`
            : `节点: ${selectedNode.id}`
        }
      />
    </div>
  );
}