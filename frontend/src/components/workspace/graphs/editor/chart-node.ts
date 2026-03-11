import { mergeAttributes, Node } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";

import { ChartNodeView } from "./chart-node-view";

export interface ChartNodeAttributes {
  chartId: string;
  title: string;
  option: Record<string, unknown>;
}

export const ChartNode = Node.create({
  name: "chartNode",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      chartId: { default: "" },
      title: { default: "" },
      option: { default: {} },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="chart-node"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-type": "chart-node" }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ChartNodeView);
  },
});
