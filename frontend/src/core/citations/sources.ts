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
// A closing fence is indentation and a marker and nothing else, so it cannot
// reuse FENCE_LINE_RE: that pattern also accepts list markers, which are plain
// content once a fence is open.
const FENCE_CLOSER_RE = /^([ \t]*)(`{3,}|~{3,})/;

// Inline spans end at a block boundary, not just at a blank line: see
// `inlineSpanStarts` for the shapes and the matching scanner in
// core/messages/utils.ts.
const BLANK_LINE_RE = /^(?:[ \t]*>)*[ \t]*$/;
const ATX_HEADING_RE = /^(?:[ \t]*>)*[ \t]{0,3}#{1,6}(?:[ \t]|$)/;
const THEMATIC_BREAK_RE =
  /^(?:[ \t]*>)*[ \t]{0,3}(?:(?:=+|-+)[ \t]*|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,})$/;
const INTERRUPTING_LIST_RE = /^(?:[ \t]*>)*[ \t]{0,3}(?:[-+*]|1[.)])[ \t]+\S/;

const INLINE_CODE_SPAN_RE = /(`+)[\s\S]*?\1/g;

// Column reached by advancing from `column` through `text`, expanding a tab to
// the next four-column stop the way CommonMark does. Character counts would make
// `-\t` two columns wide when it really reaches column four.
function advanceColumns(column: number, text: string): number {
  let reached = column;
  for (const char of text) {
    reached += char === "\t" ? 4 - (reached % 4) : 1;
  }
  return reached;
}

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

// A line split into the block quotes it sits in and the text inside the
// innermost one. One optional space or tab after the last `>` is the quote
// marker's own padding, not indentation, so it is stripped before anything is
// measured: counting it left a closer at the three-column limit reading as four
// columns and rejected.
function quoteContext(line: string): { quoteDepth: number; rest: string } {
  const quoted = BLOCKQUOTE_PREFIX_RE.exec(line)?.[0];
  if (!quoted) {
    return { quoteDepth: 0, rest: line };
  }
  return {
    quoteDepth: quoted.split(">").length - 1,
    rest: line.slice(quoted.length).replace(/^[ \t]?/, ""),
  };
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
  // After the split on "\n" a CRLF ending still carries its "\r" on the line,
  // and that "\r" is the other half of the ending rather than content: reading
  // it as body made a blank CRLF line nonblank, which cleared an indented run
  // in the middle of a code block.
  const content = line.endsWith("\r") ? line.slice(0, -1) : line;
  const { quoteDepth, rest } = quoteContext(content);
  const body = rest.replace(/^[ \t]+/, "");
  return {
    quoteDepth,
    indent: indentationColumns(rest.slice(0, rest.length - body.length)),
    body,
  };
}

// Column a fence marker starts at, measured from the content of the innermost
// blockquote. Container prefixes are part of the offset, so `- ```md` and
// `  ```md` both read as column two.
function fenceMarkerColumn(line: string, marker: string): number {
  const rest = quoteContext(line).rest;
  return advanceColumns(0, rest.slice(0, rest.indexOf(marker)));
}

// The closer a line offers, or null when it is literal content. Only
// indentation may precede the marker and nothing but whitespace may follow it.
function closingFence(line: string): { marker: string; column: number } | null {
  const rest = quoteContext(line).rest;
  const match = FENCE_CLOSER_RE.exec(rest);
  if (!match) {
    return null;
  }
  const [, indentation = "", marker = ""] = match;
  if (marker === "" || rest.slice(match[0].length).trim() !== "") {
    return null;
  }
  return { marker, column: indentationColumns(indentation) };
}

// What follows a fence marker on its line. Two CommonMark rules live there: a
// closing fence is bare, and a backtick fence's info string carries no backtick.
// Both are what the scanner in core/messages/utils.ts already enforces.
function fenceTail(line: string, match: RegExpExecArray): string {
  return line.slice(match[0].length);
}

type OpenFence = { quoteDepth: number; column: number };

// How far a line has to be indented past its container's content column to be
// an indented code block rather than a paragraph. One tab already reaches it.
const INDENTED_CODE_COLUMNS = 4;

// The content column of the deepest list item a line's indentation still keeps
// open, popping the items the line has dedented past. The scan loop applies the
// same rule before it reads a new list marker.
function survivingItemColumn(items: number[], indent: number): number {
  while (items.length > 0 && indent < (items[items.length - 1] ?? 0)) {
    items.pop();
  }
  return items[items.length - 1] ?? 0;
}

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
  // A quote can sit inside a list item, and the item outlives the quote: the
  // depth-zero stack is parked here while the quote is scanned, so a fence that
  // ends with the quote can measure against the item it sat in.
  let outerItems: number[] | null = null;
  // Leaving a block quote is not the same as reaching free text: a line four
  // columns past the surviving list item — or past column zero when there is
  // none — starts an indented code block, so its citations stay code and must
  // stay blanked. The quote can also end on a blank line, which decides
  // nothing; the exit then stays pending until the first nonblank line
  // classifies it. Blank lines inside such a run need nothing — they carry no
  // text to hide.
  let indentedRun = false;
  // The container column the active run measures its four columns against.
  let runBase = 0;
  // Set when a fence ends because its quote did, on a line too blank to tell
  // an indented code block from ordinary structure.
  let pendingQuoteExit = false;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!;
    const position = linePosition(line);
    const opener = FENCE_LINE_RE.exec(line);
    if (pendingQuoteExit) {
      if (position.quoteDepth === 0 && position.body === "") {
        continue;
      }
      pendingQuoteExit = false;
      if (position.quoteDepth === 0) {
        const base = survivingItemColumn(items, position.indent);
        if (position.indent - base >= INDENTED_CODE_COLUMNS) {
          runBase = base;
          indentedRun = true;
          lines[i] = maskKeepingNewlines(line);
          continue;
        }
      }
    }
    if (indentedRun) {
      if (
        position.quoteDepth === 0 &&
        (position.body === "" ||
          position.indent - runBase >= INDENTED_CODE_COLUMNS)
      ) {
        if (position.body !== "") {
          lines[i] = maskKeepingNewlines(line);
        }
        continue;
      }
      indentedRun = false;
    }
    if (openMarker) {
      const escaped =
        position.quoteDepth < fence!.quoteDepth ||
        (position.body !== "" && position.indent < fence!.column);
      if (escaped) {
        const leftTheQuote = fence!.quoteDepth > 0 && position.quoteDepth === 0;
        openMarker = null;
        fence = null;
        if (leftTheQuote) {
          // Returning to depth zero hands the line back to the list items the
          // quote sat in, so the four-column threshold below is measured
          // against the surviving item rather than the document root.
          items = outerItems ?? [];
          outerItems = null;
          itemsQuoteDepth = 0;
          if (position.body === "") {
            pendingQuoteExit = true;
          } else {
            runBase = survivingItemColumn(items, position.indent);
            indentedRun = position.indent - runBase >= INDENTED_CODE_COLUMNS;
            if (indentedRun) {
              lines[i] = maskKeepingNewlines(line);
            }
          }
        }
      } else {
        lines[i] = maskKeepingNewlines(line);
        // A closer is only a closer when nothing but whitespace follows the
        // marker: ` ```text ` inside a ` ``` ` block is literal content, so
        // blanking it as a fence end would let a citation on the following
        // lines surface as a phantom source.
        const closer = closingFence(line);
        if (
          closer &&
          position.quoteDepth === fence!.quoteDepth &&
          closer.column - fence!.column <= 3 &&
          closer.marker.startsWith(openMarker.charAt(0)) &&
          closer.marker.length >= openMarker.length
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
      if (itemsQuoteDepth === 0 && position.quoteDepth > 0) {
        outerItems = items;
      }
      items = [];
      itemsQuoteDepth = position.quoteDepth;
    }
    if (position.body !== "") {
      survivingItemColumn(items, position.indent);
    }
    const item = LIST_ITEM_RE.exec(position.body);
    if (item && position.indent - (items[items.length - 1] ?? 0) <= 3) {
      // The item's content column is where its marker text ends in columns, not
      // in characters: `-\t` reaches column four, and reading it as two would
      // keep a citation two spaces in inside a fence the reader already left.
      items.push(advanceColumns(position.indent, item[0]));
    }
    // The opener gets the same three-column budget as the closer: four columns
    // past the container's content column is an indented code block, so a marker
    // there cannot open a fence and everything after it keeps rendering.
    const openerMarker = opener?.[2];
    const containerColumn = items[items.length - 1] ?? 0;
    // `BLOCKQUOTE_PREFIX_RE` only matches from the start of a line, so a quote
    // opened behind a list marker - `- > ```md` - reads as depth zero even
    // though its fence really is quoted. The opener's own prefix is the truth
    // there: each `>` in it is a container the fence sits inside, and a line
    // that drops all of them has left the quote rather than reached free text.
    const prefixQuoteDepth = (opener?.[1] ?? "").split(">").length - 1;
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
        quoteDepth: Math.max(prefixQuoteDepth, position.quoteDepth),
        column: containerColumn,
      };
      if (prefixQuoteDepth > position.quoteDepth) {
        // The list items holding that quote are invisible to `quoteDepth`, so
        // park their stack here: when the fence ends on an unquoted line the
        // escape below has nothing else to measure its four columns against.
        outerItems = [...items];
      }
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
