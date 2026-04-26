"use client";

import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type OnSelectionChangeParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { nanoid } from "nanoid";
import { useCallback, useEffect } from "react";

import type { CanvasNode, CanvasEdge } from "@/core/canvas/types";

import { CanvasToolbar } from "./canvas-toolbar";
import { useCanvasContext } from "./context";
import { ExecutionStatus } from "./execution-status";
import { NodeEditor } from "./node-editor";
import { DataOutputNode } from "./nodes/data-output-node";
import { DataSourceNode } from "./nodes/data-source-node";
import { PythonScriptNode } from "./nodes/python-script-node";
import { SQLExecutorNode } from "./nodes/sql-executor-node";


const nodeTypes = {
  data_source: DataSourceNode,
  sql_executor: SQLExecutorNode,
  python_script: PythonScriptNode,
  data_output: DataOutputNode,
};

export function CanvasPanel() {
  const { canvas, setSelectedNodes, setSelectedEdges, selectedNodeId, selectNode, executionStatus } = useCanvasContext();

  // 确保 edges 有唯一 id
  const ensureEdgeIds = useCallback((edges: CanvasEdge[]): CanvasEdge[] => {
    return edges.map((edge) => ({
      ...edge,
      id: edge.id ?? `edge-${nanoid()}`,
    }));
  }, []);

  // 确保 nodes 有唯一 id
  const ensureNodeIds = useCallback((nodes: CanvasNode[]): CanvasNode[] => {
    return nodes.map((node) => ({
      ...node,
      id: node.id ?? `node-${nanoid()}`,
    }));
  }, []);

  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>([]);

  // Sync canvas data with React Flow state
  useEffect(() => {
    if (canvas) {
      setNodes(ensureNodeIds(canvas.nodes));
      setEdges(ensureEdgeIds(canvas.edges));
    }
  }, [canvas, setNodes, setEdges, ensureNodeIds, ensureEdgeIds]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge(connection, eds));
    },
    [setEdges],
  );

  const onSelectionChange = useCallback(
    ({ nodes: selectedNodes, edges: selectedEdges }: OnSelectionChangeParams<CanvasNode, CanvasEdge>) => {
      setSelectedNodes(selectedNodes.map((n) => n.id));
      setSelectedEdges(selectedEdges.map((e) => e.id));
      // 单选节点时设置 selectedNodeId 以显示 Node Editor
      if (selectedNodes.length === 1) {
        selectNode(selectedNodes[0]!.id);
      } else {
        selectNode(null);
      }
    },
    [setSelectedNodes, setSelectedEdges, selectNode],
  );

  return (
    <div className="h-full w-full flex">
      {/* Canvas DAG区域 */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onSelectionChange={onSelectionChange}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
        >
          <Controls />
          <MiniMap />
          <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        </ReactFlow>
        {/* 工具栏 */}
        <div className="absolute top-2 left-2 z-10">
          <CanvasToolbar />
        </div>
        {/* 执行状态 */}
        <div className="absolute bottom-2 left-2 z-10">
          <ExecutionStatus status={executionStatus} />
        </div>
      </div>
      {/* Node Editor侧边栏 */}
      {selectedNodeId && (
        <div className="w-64 border-l bg-background p-4">
          <NodeEditor />
        </div>
      )}
    </div>
  );
}