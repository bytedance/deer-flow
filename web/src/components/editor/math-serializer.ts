// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Mathematics } from "novel";

/**
 * Extended Mathematics extension with markdown serialization support
 * Handles both inline math ($...$) and block/display math ($$...$$)
 */
export const MathematicsWithMarkdown = Mathematics.extend({
  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const latex = node.attrs?.latex || "";
          const isBlock = node.attrs?.display === true;
          
          if (isBlock) {
            // Block/display math: $$...$$
            state.write("$$");
            state.write(latex);
            state.write("$$");
            state.closeBlock(node);
          } else {
            // Inline math: $...$
            state.write("$");
            state.write(latex);
            state.write("$");
          }
        },
      },
    };
  },
});
