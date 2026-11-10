#!/usr/bin/env node
/**
 * Read-only heuristic check for potentially untranslated JSX surface copy.
 * Reports components only, not documentation, translations or runtime data.
 * Some matches are brand names, technical identifiers and intentional fallbacks.
 */
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const base = path.resolve(__dirname, "../src");
const roots = ["components/workspace", "app/workspace"];
const skip = /(?:^|\/)(?:generated|node_modules)(?:\/|$)/;
const plainAttrs = new Set([
  "placeholder",
  "title",
  "aria-label",
  "alt",
  "label",
  "description",
]);
const results = [];
let files = 0;
function walk(dir) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (skip.test(p)) continue;
    if (entry.isDirectory()) walk(p);
    else if (/\.tsx$/.test(entry.name)) check(p);
  }
}
function check(file) {
  files++;
  const data = fs.readFileSync(file, "utf8");
  const ast = ts.createSourceFile(
    file,
    data,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const isEnglish = (text) =>
    /\b(?:the|and|your|you|please|click|open|view|select|create|failed|loading|settings|report|save|cancel|edit|delete|retry|show|search|changes|models|users|working|login|account|password|notification|help|tools|skills)\b/i.test(
      text,
    ) && !/^[A-Za-z][A-Za-z0-9 -]{0,5}$/.test(text);
  const add = (n, type, value) => {
    const val = value.replace(/\s+/g, " ").trim();
    if (val && isEnglish(val)) {
      const at = ast.getLineAndCharacterOfPosition(n.getStart(ast));
      results.push({
        file: path.relative(base, file).replace(/\\/g, "/"),
        line: at.line + 1,
        type,
        text: val.slice(0, 155),
      });
    }
  };
  function visit(n) {
    if (ts.isJsxText(n)) add(n, "jsx-text", n.text);
    if (
      ts.isJsxAttribute(n) &&
      n.initializer &&
      ts.isStringLiteral(n.initializer)
    ) {
      if (plainAttrs.has(n.name.getText(ast)))
        add(n, "jsx-" + n.name.getText(ast), n.initializer.text);
    }
    ts.forEachChild(n, visit);
  }
  visit(ast);
}
for (const root of roots) walk(path.join(base, root));
const summary = {
  filesScanned: files,
  candidates: results.length,
  items: results,
};
console.log(JSON.stringify(summary, null, 2));
