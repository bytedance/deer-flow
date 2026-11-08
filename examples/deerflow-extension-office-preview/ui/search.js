/** Literal matches across styled runs, with no HTML insertion. */
export function highlightText(root, query) {
  root
    .querySelectorAll("mark[data-office-match]")
    .forEach((mark) => mark.replaceWith(...mark.childNodes));
  root.normalize();
  if (!query.trim()) return [];
  const groups = [];
  const blocks = [
    ...root.querySelectorAll("p,td,th,li,h1,h2,h3,h4,h5,h6"),
  ].filter((node) => !node.querySelector("p,td,th,li,h1,h2,h3,h4,h5,h6"));
  if (!blocks.length) blocks.push(root);
  const pattern = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (const block of blocks) {
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) =>
        node.parentElement.closest("style,script")
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT,
    });
    const nodes = [];
    let text = "",
      node;
    while ((node = walker.nextNode())) {
      nodes.push({ node, start: text.length });
      text += node.textContent;
    }
    const matches = [...text.matchAll(new RegExp(pattern, "giu"))];
    const local = matches.map(() => []);
    for (const { node: textNode, start } of nodes) {
      const content = textNode.textContent,
        fragment = document.createDocumentFragment();
      let cursor = 0;
      matches.forEach((match, index) => {
        const from = Math.max(0, match.index - start),
          to = Math.min(content.length, match.index + match[0].length - start);
        if (from >= to) return;
        fragment.append(document.createTextNode(content.slice(cursor, from)));
        const mark = document.createElement("mark");
        mark.dataset.officeMatch = "";
        mark.textContent = content.slice(from, to);
        fragment.append(mark);
        local[index].push(mark);
        cursor = to;
      });
      if (cursor) {
        fragment.append(document.createTextNode(content.slice(cursor)));
        textNode.replaceWith(fragment);
      }
    }
    groups.push(...local.filter((group) => group.length));
  }
  return groups;
}

/** Add private bookmarks only to the preview copy, so outline targets survive page layout. */
export async function prepareWordOutline(zip) {
  const parse = (xml) =>
    new DOMParser().parseFromString(xml, "application/xml");
  const attr = (node, name) =>
    node?.getAttributeNS(
      "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      name,
    );
  const child = (node, name) =>
    [...(node?.children ?? [])].find((entry) => entry.localName === name);
  const styles = new Map();
  const source = zip.file("word/styles.xml");
  if (source)
    for (const style of parse(
      await source.async("string"),
    ).getElementsByTagNameNS("*", "style")) {
      styles.set(attr(style, "styleId"), {
        level: attr(child(child(style, "pPr"), "outlineLvl"), "val"),
        base: attr(child(style, "basedOn"), "val"),
      });
    }
  const resolveLevel = (id, visited = new Set()) => {
    if (!id || visited.has(id)) return undefined;
    visited.add(id);
    const style = styles.get(id);
    return style?.level ?? resolveLevel(style?.base, visited);
  };
  const file = zip.file("word/document.xml");
  if (!file) return [];
  const xml = parse(await file.async("string")),
    outline = [],
    prefix = `office-${crypto.randomUUID()}-`;
  for (const paragraph of xml.getElementsByTagNameNS("*", "p")) {
    const props = child(paragraph, "pPr");
    const level = Number(
      attr(child(props, "outlineLvl"), "val") ??
        resolveLevel(attr(child(props, "pStyle"), "val")) ??
        9,
    );
    const title = [...paragraph.getElementsByTagNameNS("*", "t")]
      .map((node) => node.textContent)
      .join("")
      .trim();
    if (level < 0 || level > 8 || !title) continue;
    const id = `${prefix}${outline.length}`;
    const bookmark = xml.createElementNS(
      paragraph.namespaceURI,
      "w:bookmarkStart",
    );
    bookmark.setAttributeNS(paragraph.namespaceURI, "w:name", id);
    bookmark.setAttributeNS(
      paragraph.namespaceURI,
      "w:id",
      String(100000 + outline.length),
    );
    paragraph.insertBefore(
      bookmark,
      props?.nextSibling ?? paragraph.firstChild,
    );
    const end = xml.createElementNS(paragraph.namespaceURI, "w:bookmarkEnd");
    end.setAttributeNS(
      paragraph.namespaceURI,
      "w:id",
      String(100000 + outline.length),
    );
    paragraph.append(end);
    outline.push({ id, title, level });
  }
  zip.file("word/document.xml", new XMLSerializer().serializeToString(xml));
  return outline;
}
