#!/usr/bin/env node
/**
 * Static i18n coverage audit for the Russian UI dictionary.
 *
 * Extracts public translation keys from TypeScript object literals without
 * executing functions or loading user configuration, then compares the English
 * source with explicit Russian overrides (inherited keys remain untranslated).
 *
 * Run: node scripts/audit-ru-localization.cjs
 */
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const loc = path.resolve(__dirname, "../src/core/i18n/locales");
function source(filename) {
  const code = fs.readFileSync(path.join(loc, filename), "utf8");
  return ts.createSourceFile(
    filename,
    code,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );
}
function findDictionary(ast, name) {
  for (const stmt of ast.statements) {
    if (!ts.isVariableStatement(stmt)) continue;
    for (const declaration of stmt.declarationList.declarations) {
      if (
        declaration.name.getText(ast) === name &&
        declaration.initializer &&
        ts.isObjectLiteralExpression(declaration.initializer)
      ) {
        return declaration.initializer;
      }
    }
  }
  throw new Error("Dictionary not found: " + name);
}
function isTranslatedValue(value) {
  if (
    ts.isStringLiteral(value) ||
    ts.isNoSubstitutionTemplateLiteral(value) ||
    ts.isTemplateExpression(value) ||
    ts.isArrowFunction(value) ||
    ts.isFunctionExpression(value)
  )
    return true;
  if (ts.isArrayLiteralExpression(value)) return true; // Suggestion lists.
  return false;
}
function entries(obj, prefix = "", output = new Map()) {
  for (const prop of obj.properties) {
    if (!ts.isPropertyAssignment(prop)) continue;
    const name = prop.name;
    const key =
      ts.isIdentifier(name) ||
      ts.isStringLiteral(name) ||
      ts.isNumericLiteral(name)
        ? name.text
        : name.getText();
    const full = prefix ? prefix + "." + key : key;
    const val = prop.initializer;
    if (ts.isObjectLiteralExpression(val)) {
      entries(val, full, output);
    } else if (isTranslatedValue(val)) {
      output.set(full, val.getText().replace(/\s+/g, " ").slice(0, 230));
    }
  }
  return output;
}
const english = entries(findDictionary(source("en-US.ts"), "enUS"));
const russian = entries(findDictionary(source("ru-RU.ts"), "ruRU"));
const covered = [...english.keys()].filter((k) => russian.has(k));
const missing = [...english.keys()].filter((k) => !russian.has(k));
const group = {};
for (const k of english.keys()) {
  const name = k.split(".")[0];
  group[name] ??= { total: 0, translated: 0, missing: [] };
  group[name].total++;
  if (russian.has(k)) group[name].translated++;
  else group[name].missing.push(k);
}
console.log(
  JSON.stringify(
    {
      summary: {
        englishKeys: english.size,
        explicitRussianKeys: covered.length,
        notExplicitlyTranslated: missing.length,
        percent: Math.round((100 * covered.length) / english.size),
      },
      groups: Object.fromEntries(
        Object.entries(group).map(([k, v]) => [
          k,
          {
            total: v.total,
            translated: v.translated,
            remaining: v.total - v.translated,
          },
        ]),
      ),
      topMissing: missing.slice(0, 100),
      allMissing: process.argv.includes("--all")
        ? missing.map((key) => ({ key, english: english.get(key) }))
        : undefined,
    },
    null,
    2,
  ),
);
