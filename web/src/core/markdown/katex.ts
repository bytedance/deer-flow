// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { Options as RehypeKatexOptions } from "rehype-katex";

import "katex/contrib/mhchem";

const macros = {
  "\\vect": "\\mathbf{#1}",
  "\\mat": "\\mathbf{#1}",
  "\\grad": "\\nabla #1",
  "\\div": "\\nabla \\cdot #1",
  "\\curl": "\\nabla \\times #1",
  "\\dv": "\\frac{d #1}{d #2}",
  "\\pdv": "\\frac{\\partial #1}{\\partial #2}",
  "\\pdvN": "\\frac{\\partial^{#3} #1}{\\partial #2^{#3}}",
  "\\abs": "\\left|#1\\right|",
  "\\norm": "\\left\\lVert#1\\right\\rVert",
  "\\set": "\\left\\{#1\\right\\}",
  "\\bra": "\\left\\langle#1\\right|",
  "\\ket": "\\left|#1\\right\\rangle",
  "\\braket": "\\left\\langle#1\\middle|#2\\right\\rangle",
  "\\matrix": "\\begin{pmatrix}#1\\end{pmatrix}",
} as const;

export const katexOptions: RehypeKatexOptions = {
  macros,
  strict: "ignore",
  throwOnError: false,
  trust: (context) => context.command === "\\htmlClass" || context.command === "\\href",
};

export type KatexMacroKey = keyof typeof macros;
