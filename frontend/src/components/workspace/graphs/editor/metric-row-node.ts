import { mergeAttributes, Node } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";

import { MetricRowNodeView } from "./metric-row-node-view";

export interface MetricItem {
  metricId: string;
  label: string;
  value: string;
  change?: string;
}

export const MetricRowNode = Node.create({
  name: "metricRowNode",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      metrics: { default: [] },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="metric-row-node"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-type": "metric-row-node" }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(MetricRowNodeView);
  },
});
