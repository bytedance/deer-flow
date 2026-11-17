import { DOMParser, XMLSerializer } from "@xmldom/xmldom";

// Only the namespace/tag descendant selectors used by the pinned PPT converter.
// Unknown selector syntax fails explicitly rather than returning incorrect output.
function selectors(value) {
  return value.split(",").map((group) =>
    group
      .trim()
      .split(/\s+/)
      .map((token) => {
        const name = token.replaceAll("\\:", ":");
        if (!/^(?:\*\|)?[A-Za-z_][\w.:-]*$/.test(name))
          throw new Error("Unsupported Office XML selector");
        return name;
      }),
  );
}
function matches(node, name) {
  return name.startsWith("*|")
    ? node.localName === name.slice(2)
    : node.tagName === name;
}
function queryAll(root, selector) {
  const groups = selectors(selector),
    found = [];
  for (const node of root.getElementsByTagName("*")) {
    if (
      groups.some((group) => {
        if (!matches(node, group.at(-1))) return false;
        let parent = node.parentElement;
        for (let i = group.length - 2; i >= 0; i--) {
          while (
            parent &&
            parent !== root.parentElement &&
            !matches(parent, group[i])
          )
            parent = parent.parentElement;
          if (!parent || parent === root.parentElement) return false;
          parent = parent.parentElement;
        }
        return true;
      })
    )
      found.push(node);
  }
  return found;
}
export class WorkerXmlParser extends DOMParser {
  constructor() {
    super({
      onError: () => {
        throw new Error("Invalid Office XML");
      },
    });
  }
  parseFromString(xml, type) {
    const doc = super.parseFromString(xml, type);
    for (const prototype of [
      Object.getPrototypeOf(doc),
      Object.getPrototypeOf(doc.documentElement),
    ]) {
      if (!Object.getOwnPropertyDescriptor(prototype, "firstElementChild"))
        Object.defineProperty(prototype, "firstElementChild", {
          get() {
            return (
              [...this.childNodes].find((node) => node.nodeType === 1) ?? null
            );
          },
        });
      if (!prototype.querySelectorAll)
        Object.defineProperties(prototype, {
          querySelectorAll: {
            value(selector) {
              return queryAll(this, selector);
            },
          },
          querySelector: {
            value(selector) {
              return queryAll(this, selector)[0] ?? null;
            },
          },
        });
    }
    return doc;
  }
}
export function installWorkerXml() {
  // Never provide a fake browser Window or document. Rendering stays in the UI.
  globalThis.DOMParser = WorkerXmlParser;
  globalThis.XMLSerializer = XMLSerializer;
  globalThis.Node = { ELEMENT_NODE: 1 };
}
