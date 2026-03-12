import { mergeAttributes, Node } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";

import { MetricNodeView } from "./metric-node-view";

export interface MetricNodeAttributes {
  metricId: string;
  label: string;
  value: string;
  change?: string;
}

export const MetricNode = Node.create({
  name: "metricNode",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      metricId: { default: "" },
      label: { default: "" },
      value: { default: "" },
      change: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="metric-node"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-type": "metric-node" }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(MetricNodeView);
  },
});
