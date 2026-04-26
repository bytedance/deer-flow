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
import { useCallback, useEffect } from "react";

import { useCanvasContext } from "./context";
import { DataSourceNode } from "./nodes/data-source-node";
import { SQLExecutorNode } from "./nodes/sql-executor-node";
import { PythonScriptNode } from "./nodes/python-script-node";
import { DataOutputNode } from "./nodes/data-output-node";

import type { CanvasNode, CanvasEdge } from "@/core/canvas/types";

const nodeTypes = {
  data_source: DataSourceNode,
  sql_executor: SQLExecutorNode,
  python_script: PythonScriptNode,
  data_output: DataOutputNode,
};

export function CanvasPanel() {
  const { canvas, setSelectedNodes, setSelectedEdges } = useCanvasContext();

  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>(canvas?.nodes ?? []);
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>(canvas?.edges ?? []);

  // Sync canvas data with React Flow state
  useEffect(() => {
    if (canvas) {
      setNodes(canvas.nodes);
      setEdges(canvas.edges);
    }
  }, [canvas, setNodes, setEdges]);

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
    },
    [setSelectedNodes, setSelectedEdges],
  );

  return (
    <div className="h-full w-full">
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
    </div>
  );
}