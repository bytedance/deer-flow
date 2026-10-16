import { parse } from "@babel/parser";

interface Range {
  start: number;
  end: number;
}
export interface HTMLModulePlan {
  text: string;
  imports: (Range & { reference: string })[];
  dynamic: (Range & { argumentStart: number; hasOptions: boolean })[];
  meta: Range[];
}

/** Parse actual module syntax; strings/comments are never import instructions. */
export function planHTMLModule(text: string): HTMLModulePlan {
  const plan: HTMLModulePlan = { text, imports: [], dynamic: [], meta: [] };
  let ast: unknown;
  try {
    ast = parse(text, {
      sourceType: "module",
      createImportExpressions: true,
      plugins: ["importAttributes"],
    });
  } catch {
    return plan;
  } // Let the native browser report invalid/unsupported syntax.
  const record = (value: unknown): Record<string, unknown> | undefined =>
    value !== null && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : undefined;
  const range = (node: Record<string, unknown> | undefined) =>
    node && typeof node.start === "number" && typeof node.end === "number"
      ? { start: node.start, end: node.end }
      : undefined;
  const visit = (value: unknown) => {
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
      return;
    }
    const node = record(value);
    if (!node || typeof node.type !== "string") return;
    const position = range(node);
    if (
      [
        "ImportDeclaration",
        "ExportNamedDeclaration",
        "ExportAllDeclaration",
      ].includes(node.type)
    ) {
      const source = record(node.source);
      const sourceRange = range(source);
      if (
        source?.type === "StringLiteral" &&
        typeof source.value === "string" &&
        sourceRange
      )
        plan.imports.push({ ...sourceRange, reference: source.value });
    } else if (node.type === "ImportExpression" && position) {
      const sourceRange = range(record(node.source));
      if (sourceRange)
        plan.dynamic.push({
          ...position,
          argumentStart: sourceRange.start,
          hasOptions: node.options != null,
        });
    } else if (
      node.type === "MetaProperty" &&
      position &&
      record(node.meta)?.name === "import" &&
      record(node.property)?.name === "meta"
    )
      plan.meta.push(position);
    for (const child of Object.values(node)) visit(child);
  };
  visit(ast);
  return plan;
}
