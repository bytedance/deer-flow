import { parse, serialize, type DefaultTreeAdapterMap } from "parse5";
import postcss from "postcss";
import valueParser from "postcss-value-parser";

import { planHTMLModule, type HTMLModulePlan } from "./html-module-plan";
import type { createHTMLArtifactResourceReader } from "./html-resource-reader";

type Reader = ReturnType<typeof createHTMLArtifactResourceReader>;
export interface HTMLResourceEdit {
  start: number;
  end: number;
  reference: string;
  kind: "asset" | "css";
}
export interface HTMLCSSPlan {
  text: string;
  edits: HTMLResourceEdit[];
}

// CSS syntax is parsed, rather than matching url() inside comments or strings.
export function planHTMLStylesheet(text: string): HTMLCSSPlan {
  const edits: HTMLResourceEdit[] = [];
  const collect = (value: string, offset: number, isImport: boolean) => {
    const parsed = valueParser(value);
    if (isImport) {
      const first = parsed.nodes.find(
        (node) => node.type !== "space" && node.type !== "comment",
      );
      if (first?.type === "string")
        edits.push({
          start: offset + first.sourceIndex,
          end: offset + first.sourceEndIndex,
          reference: decodeCSSReference(first.value),
          kind: "css",
        });
    }
    parsed.walk((node) => {
      if (
        node.type !== "function" ||
        decodeCSSReference(node.value).toLowerCase() !== "url"
      )
        return;
      const argument = node.nodes.filter(
        (part) => part.type !== "space" && part.type !== "comment",
      );
      const part = argument[0];
      if (
        argument.length === 1 &&
        part &&
        (part.type === "string" || part.type === "word")
      )
        edits.push({
          start: offset + part.sourceIndex,
          end: offset + part.sourceEndIndex,
          reference: decodeCSSReference(part.value),
          kind: isImport ? "css" : "asset",
        });
      return false;
    });
  };
  postcss.parse(text).walk((node) => {
    const offset = node.source?.start?.offset;
    if (offset === undefined) return;
    if (node.type === "decl") {
      const raw = node.raws.value?.raw ?? node.value;
      collect(
        raw,
        offset + node.prop.length + (node.raws.between ?? ":").length,
        false,
      );
    } else if (node.type === "atrule" && node.name.toLowerCase() === "import") {
      const raw = node.raws.params?.raw ?? node.params;
      collect(
        raw,
        offset + 1 + node.name.length + (node.raws.afterName ?? "").length,
        true,
      );
    }
  });
  return { text, edits };
}

function decodeCSSReference(value: string) {
  return value.replace(
    /\\([0-9a-f]{1,6}\s?|\r\n|[\s\S])/gi,
    (_match, escaped: string) => {
      if (/^[0-9a-f]/i.test(escaped)) {
        const code = parseInt(escaped.trim(), 16);
        return code === 0 ||
          code > 0x10ffff ||
          (code >= 0xd800 && code <= 0xdfff)
          ? "\ufffd"
          : String.fromCodePoint(code);
      }
      return /^[\r\n\f]/.test(escaped) ? "" : escaped;
    },
  );
}

export interface HTMLDocumentResource {
  token: string;
  reference?: string;
  kind: "asset" | "css" | "module";
  css?: HTMLCSSPlan;
  module?: HTMLModulePlan;
  attribute?: boolean;
}

/** Pure HTML parser: preparing a report never creates fetching DOM elements. */
export function planHTMLDocument(
  content: string,
  reader: Reader,
  nonce: string,
) {
  const document = parse(content);
  const resources: HTMLDocumentResource[] = [];
  let baseURL = reader.sourceURL;
  const visit = (
    node: DefaultTreeAdapterMap["node"],
    fn: (node: DefaultTreeAdapterMap["element"]) => void,
  ) => {
    if ("tagName" in node) {
      fn(node);
      if (node.tagName === "template") return;
    }
    if ("childNodes" in node)
      for (const child of node.childNodes) visit(child, fn);
  };
  let foundBase = false;
  visit(document, (node) => {
    if (node.tagName !== "base" || foundBase) return;
    const href = node.attrs.find((attr) => attr.name === "href");
    if (!href) return;
    foundBase = true;
    try {
      baseURL = new URL(href.value, reader.sourceURL).href;
      href.value = baseURL;
    } catch {
      href.value = reader.sourceURL;
    }
  });
  const tokenFor = (resource: Omit<HTMLDocumentResource, "token">) => {
    const token = `deerflow-resource-${nonce}-${resources.length}`;
    resources.push({ ...resource, token });
    return token;
  };
  visit(document, (node) => {
    const isModule =
      node.tagName === "script" &&
      node.attrs.some(
        (attr) =>
          attr.name === "type" && attr.value.trim().toLowerCase() === "module",
      );
    if (isModule && !node.attrs.some((attr) => attr.name === "src")) {
      const text = node.childNodes
        .map((child) => ("value" in child ? child.value : ""))
        .join("");
      node.childNodes = [];
      node.attrs.push({
        name: "src",
        value: tokenFor({
          kind: "module",
          module: planHTMLModule(text),
          attribute: true,
        }),
      });
      return;
    }
    for (const attr of node.attrs) {
      if (attr.name === "style") {
        attr.value = tokenFor({
          kind: "css",
          css: planHTMLStylesheet(`x{${attr.value}}`),
          attribute: true,
        });
      } else if (node.tagName === "a" && attr.name === "href") {
        attr.value = reader.resolve(attr.value, baseURL) ?? attr.value;
      } else if (
        (attr.name === "src" &&
          [
            "img",
            "script",
            "audio",
            "video",
            "source",
            "input",
            "track",
          ].includes(node.tagName)) ||
        (attr.name === "poster" && node.tagName === "video") ||
        (node.tagName === "link" &&
          attr.name === "href" &&
          node.attrs.some(
            (a) =>
              a.name === "rel" &&
              a.value.toLowerCase().split(/\s+/).includes("stylesheet"),
          ))
      ) {
        attr.value = tokenFor({
          reference: attr.value,
          kind: isModule ? "module" : node.tagName === "link" ? "css" : "asset",
          attribute: true,
        });
      }
    }
    if (node.tagName === "style") {
      for (const child of node.childNodes)
        if ("value" in child && child.nodeName === "#text")
          child.value = tokenFor({
            kind: "css",
            css: planHTMLStylesheet(child.value),
          });
    }
  });
  return {
    html: serialize(document),
    resources,
    baseURL,
    sourceURL: reader.sourceURL,
  };
}
