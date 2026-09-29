export type CitationOccurrence = {
  index: number;
  title: string;
};

export type CitationSource = {
  id: string;
  title: string;
  url: string;
  domain: string;
  count: number;
  occurrences: CitationOccurrence[];
};

// Uses a non-consuming lookbehind (?<!!) to skip image links (![citation:…])
// without eating the boundary char, so back-to-back citations both match. The
// URL sub-pattern consumes either non-paren chars or a balanced (…) group, so
// disambiguation URLs like .../Foo_(a)_(b) survive rather than truncating at
// the first inner paren.
const CITATION_LINK_RE =
  /(?<!!)\[citation:\s*([^\]]+?)\]\((https?:\/\/(?:[^\s()]|\([^\s()]*\))+)\)/gi;

const GENERIC_CITATION_TITLES = new Set(["source", "来源"]);

export function extractCitationSources(markdown: string): CitationSource[] {
  if (!markdown) {
    return [];
  }

  const searchable = maskCitationCode(markdown);
  const sourcesByUrl = new Map<string, CitationSource>();

  for (const match of searchable.matchAll(CITATION_LINK_RE)) {
    const rawTitle = (match[1] ?? "").trim();
    const rawUrl = match[2] ?? "";
    const url = normalizeUrl(rawUrl);
    if (!url) {
      continue;
    }

    const domain = extractDomain(url);
    const title = normalizeTitle(rawTitle, domain);
    const index = match.index ?? 0;
    const existing = sourcesByUrl.get(url);

    if (existing) {
      existing.count += 1;
      existing.occurrences.push({ index, title });
      continue;
    }

    sourcesByUrl.set(url, {
      id: url,
      title,
      url,
      domain,
      count: 1,
      occurrences: [{ index, title }],
    });
  }

  return Array.from(sourcesByUrl.values());
}

export function formatCitationMarkdownReference(
  source: CitationSource,
): string {
  return `[${source.title}](${source.url})`;
}

function normalizeTitle(title: string, domain: string): string {
  const compact = title.replace(/\s+/g, " ").trim();
  if (!compact || GENERIC_CITATION_TITLES.has(compact.toLowerCase())) {
    return domain;
  }
  return compact;
}

function normalizeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url.href;
  } catch {
    return null;
  }
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}

// Blanks out code regions so example citations inside code aren't scraped as
// real sources, while preserving string length (and newlines) so occurrence
// indices stay aligned with the original markdown.
export function maskCitationCode(markdown: string): string {
  return maskInlineCode(maskFencedCodeBlocks(markdown));
}

// A fence can be nested in a list item or a blockquote, so its marker may sit
// behind container prefixes and the indentation a container gives it. Only the
// column-0 shape was recognised before, and indented fences were blanked by
// accident because whole-document backtick pairing happened to close them.
// Anchored: a backtick run further into a line is inline code, not an opener.
// A list marker only opens a container when whitespace follows it, so `-```md`
// is paragraph text rather than a fence opener.
const FENCE_LINE_RE =
  /^((?:(?:[ \t]*>)|(?:[-+*]|\d{1,9}[.)])[ \t]|[ \t])*)(`{3,}|~{3,})/;
const BLOCKQUOTE_PREFIX_RE = /^(?:[ \t]*>)+/;
const LIST_ITEM_RE = /^(?:[-+*]|\d{1,9}[.)])[ \t]+/;

// Inline spans end at a block boundary, not just at a blank line: see
// `inlineSpanStarts` for the shapes and the matching scanner in
// core/messages/utils.ts.
const BLANK_LINE_RE = /^(?:[ \t]*>)*[ \t]*$/;
const ATX_HEADING_RE = /^(?:[ \t]*>)*[ \t]{0,3}#{1,6}(?:[ \t]|$)/;
const THEMATIC_BREAK_RE =
  /^(?:[ \t]*>)*[ \t]{0,3}(?:(?:=+|-+)[ \t]*|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,})$/;
const INTERRUPTING_LIST_RE = /^(?:[ \t]*>)*[ \t]{0,3}(?:[-+*]|1[.)])[ \t]+\S/;

const INLINE_CODE_SPAN_RE = /(`+)[\s\S]*?\1/g;

function indentationColumns(text: string): number {
  let column = 0;
  for (const char of text) {
    if (char !== " " && char !== "\t") {
      break;
    }
    column += char === "\t" ? 4 - (column % 4) : 1;
  }
  return column;
}

// Where a line sits once its blockquote markers are stripped: how deep in the
// quotes it is, the column its content starts at inside them, and the text after
// that indentation. A line that loses a `>` has left the blockquote that held
// the fence, which is why the depth is counted rather than tested as a boolean.
function linePosition(line: string): {
  quoteDepth: number;
  indent: number;
  body: string;
} {
  const quoted = BLOCKQUOTE_PREFIX_RE.exec(line)?.[0] ?? "";
  const rest = line.slice(quoted.length);
  const body = rest.replace(/^[ \t]+/, "");
  return {
    quoteDepth: quoted.split(">").length - 1,
    indent: indentationColumns(rest.slice(0, rest.length - body.length)),
    body,
  };
}

// Column a fence marker starts at, measured from the content of the innermost
// blockquote. Container prefixes are part of the offset, so `- ```md` and
// `  ```md` both read as column two.
function fenceMarkerColumn(line: string, marker: string): number {
  const quoted = BLOCKQUOTE_PREFIX_RE.exec(line)?.[0] ?? "";
  const rest = line.slice(quoted.length);
  return rest.indexOf(marker);
}

// What follows a fence marker on its line. Two CommonMark rules live there: a
// closing fence is bare, and a backtick fence's info string carries no backtick.
// Both are what the scanner in core/messages/utils.ts already enforces.
function fenceTail(line: string, match: RegExpExecArray): string {
  return line.slice(match[0].length);
}

type OpenFence = { quoteDepth: number; column: number };

function maskFencedCodeBlocks(markdown: string): string {
  // Blank a fenced block from its opener to its matching closer — or, while the
  // message is still streaming, to end of input when the fence is unclosed.
  // Marker-aware like the shared FENCE_MARKER_RE: a closer must repeat the
  // opener character and be at least as long, so a shorter run inside the block
  // does not close it early.
  //
  // A fence also cannot outlive the container it was opened in, and the marker's
  // own indentation is not part of that container: up to three columns of it are
  // allowed anywhere, so `  ```md` at the top level keeps swallowing an
  // unindented sample line, while the same two columns inside a list item whose
  // content starts at column two end the fence as soon as a line drops back to
  // column zero. `items` is what tells those two apart.
  const lines = markdown.split("\n");
  let openMarker: string | null = null;
  let fence: OpenFence | null = null;
  let items: number[] = [];
  let itemsQuoteDepth = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!;
    const position = linePosition(line);
    const opener = FENCE_LINE_RE.exec(line);
    if (openMarker) {
      const escaped =
        position.quoteDepth < fence!.quoteDepth ||
        (position.body !== "" && position.indent < fence!.column);
      if (escaped) {
        openMarker = null;
        fence = null;
      } else {
        lines[i] = maskKeepingNewlines(line);
        const closer = opener?.[2];
        // A closer is only a closer when nothing but whitespace follows the
        // marker: ` ```text ` inside a ` ``` ` block is literal content, so
        // blanking it as a fence end would let a citation on the following
        // lines surface as a phantom source.
        const closerTail = opener ? fenceTail(line, opener) : "";
        if (
          closer &&
          closerTail.trim() === "" &&
          position.quoteDepth === fence!.quoteDepth &&
          fenceMarkerColumn(line, closer) - fence!.column <= 3 &&
          closer.startsWith(openMarker.charAt(0)) &&
          closer.length >= openMarker.length
        ) {
          openMarker = null;
          fence = null;
        }
        continue;
      }
    }
    // Outside a fence the line is structure again, so it can open or close a
    // list item. Blank lines neither end an item nor start one.
    if (position.quoteDepth !== itemsQuoteDepth) {
      items = [];
      itemsQuoteDepth = position.quoteDepth;
    }
    while (
      position.body !== "" &&
      items.length > 0 &&
      position.indent < (items[items.length - 1] ?? 0)
    ) {
      items.pop();
    }
    const item = LIST_ITEM_RE.exec(position.body);
    if (item && position.indent - (items[items.length - 1] ?? 0) <= 3) {
      items.push(position.indent + item[0].length);
    }
    // The opener gets the same three-column budget as the closer: four columns
    // past the container's content column is an indented code block, so a marker
    // there cannot open a fence and everything after it keeps rendering.
    const openerMarker = opener?.[2];
    const containerColumn = items[items.length - 1] ?? 0;
    // A backtick fence's info string cannot hold a backtick, so ` ```md `x` `
    // is paragraph text with an inline span rather than an opener; opening a
    // fence there would blank a citation the reader can actually click. Tilde
    // fences take any info string.
    const openerTail = opener ? fenceTail(line, opener) : "";
    const infoAllowed =
      !openerMarker ||
      openerMarker.startsWith("~") ||
      !openerTail.includes("`");
    if (
      openerMarker &&
      infoAllowed &&
      fenceMarkerColumn(line, openerMarker) - containerColumn <= 3
    ) {
      openMarker = openerMarker;
      fence = {
        quoteDepth: position.quoteDepth,
        column: containerColumn,
      };
      lines[i] = maskKeepingNewlines(line);
    }
  }
  return lines.join("\n");
}

function maskInlineCode(markdown: string): string {
  // Only mask closed spans: an unclosed backtick run renders as literal text,
  // so a citation after it is a real, rendered link and must not be masked.
  // Pairing stays inside one inline span, because a span cannot reach past the
  // block boundary that ends its line; without that limit a stray backtick in
  // an earlier block steals the opener of a later span and mis-pairs both
  // directions. Chunk offsets tile the input, so occurrence indices stay aligned.
  const starts = inlineSpanStarts(markdown);
  if (starts.length === 1) {
    return markdown.replace(INLINE_CODE_SPAN_RE, maskKeepingNewlines);
  }
  return starts
    .map((start, i) =>
      markdown
        .slice(start, starts[i + 1] ?? markdown.length)
        .replace(INLINE_CODE_SPAN_RE, maskKeepingNewlines),
    )
    .join("");
}

// Offsets where a new inline span context starts, mirroring the delimiters the
// reasoning scanner in core/messages/utils.ts applies: blank lines (including a
// blockquote's empty continuation line), ATX headings, thematic breaks / setext
// underlines and interrupting list items. A heading or break ends a span on
// both sides of its own line; a list item only starts a new context, since its
// own wrapped lines continue the span. An ordered item interrupts only when it
// numbers 1, matching CommonMark.
function inlineSpanStarts(markdown: string): number[] {
  const lines = markdown.split("\n");
  const starts: number[] = [0];
  let offset = 0;
  let closesPrevious = false;
  for (const line of lines) {
    const compact = line.endsWith("\r") ? line.slice(0, -1) : line;
    const closes =
      ATX_HEADING_RE.test(compact) || THEMATIC_BREAK_RE.test(compact);
    if (
      closesPrevious ||
      closes ||
      BLANK_LINE_RE.test(compact) ||
      INTERRUPTING_LIST_RE.test(compact)
    ) {
      if (offset > 0 && offset !== starts[starts.length - 1]) {
        starts.push(offset);
      }
    }
    closesPrevious = closes;
    offset += line.length + 1;
  }
  return starts;
}

function maskKeepingNewlines(block: string): string {
  return block.replace(/[^\n]/g, " ");
}
