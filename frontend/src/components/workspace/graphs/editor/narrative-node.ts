import { mergeAttributes, Node } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";

import { NarrativeNodeView } from "./narrative-node-view";

export const NarrativeNode = Node.create({
  name: "narrativeNode",
  group: "block",
  draggable: true,
  // content allows editable rich text inside
  content: "block+",

  addAttributes() {
    return {
      narrativeId: { default: "" },
      title: { default: "Executive Summary" },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="narrative-node"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-type": "narrative-node" }),
      0, // slot for content
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(NarrativeNodeView);
  },
});
