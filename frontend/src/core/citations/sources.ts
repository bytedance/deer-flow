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
  knowledge?: RetrievalSource;
};

export type RetrievalSource = {
  id: string;
  provider: string;
  title: string;
  excerpt: string;
  dataset_name?: string;
  url?: string;
  page?: number;
};

/** Sanitization prefixes fragment destinations to prevent DOM clobbering. */
export function retrievalSourceId(href: string | undefined): string | null {
  return (
    /^#(?:user-content-)?knowledge-source-([a-f0-9]{32})$/.exec(
      href ?? "",
    )?.[1] ?? null
  );
}

/** SDK message objects are immutable; cache per object without retaining history. */
export function createKnowledgeSourceReader() {
  const cache = new WeakMap<object, RetrievalSource[]>();
  return (message: object): RetrievalSource[] => {
    let sources = cache.get(message);
    if (!sources) {
      sources = readKnowledgeSources([message]);
      cache.set(message, sources);
    }
    return sources;
  };
}

const KNOWLEDGE_REFERENCE_RE =
  /(?<!!)\[citation:\s*((?:\\.|[^\]\\])+?)\]\((#knowledge-source-[a-f0-9]{32})\)/gi;

function exceedsTextLimit(text: string, limit: number): boolean {
  // JSON Schema/Pydantic count code points; avoid allocating for short text.
  return text.length > limit && [...text].length > limit;
}

/** Sources are accepted only from evidence-bearing tool artifacts, including replay. */
export function readKnowledgeSources(
  messages: readonly unknown[],
): RetrievalSource[] {
  const sources = new Map<string, RetrievalSource>();
  for (const value of messages) {
    if (!value || typeof value !== "object") continue;
    const message = value as Record<string, unknown>;
    if (message.type !== "tool" || typeof message.content !== "string")
      continue;
    const artifact = message.artifact as Record<string, unknown> | undefined;
    const rawSources = Array.isArray(artifact?.knowledge_sources)
      ? artifact.knowledge_sources
      : artifact?.retrieval_sources;
    if (artifact?.knowledge_sources_version !== 1 || !Array.isArray(rawSources))
      continue;
    for (const raw of rawSources.slice(0, 100) as unknown[]) {
      if (!raw || typeof raw !== "object") continue;
      const source = raw as Record<string, unknown>;
      if (
        typeof source.id !== "string" ||
        !/^[a-f0-9]{32}$/.test(source.id) ||
        typeof source.provider !== "string" ||
        !source.provider.trim() ||
        exceedsTextLimit(source.provider, 100) ||
        typeof source.title !== "string" ||
        !source.title.trim() ||
        exceedsTextLimit(source.title, 500) ||
        typeof source.excerpt !== "string" ||
        !source.excerpt.trim() ||
        exceedsTextLimit(source.excerpt, 100_000) ||
        (source.dataset_name !== undefined &&
          (typeof source.dataset_name !== "string" ||
            exceedsTextLimit(source.dataset_name, 500)))
      )
        continue;
      if (
        source.page !== undefined &&
        (!Number.isSafeInteger(source.page) || (source.page as number) <= 0)
      )
        continue;
      if (
        source.url !== undefined &&
        (typeof source.url !== "string" || !normalizeUrl(source.url))
      )
        continue;
      if (
        !message.content.includes(source.excerpt) ||
        !message.content.includes(`#knowledge-source-${source.id}`)
      )
        continue;
      sources.set(source.id, {
        id: source.id,
        provider: source.provider,
        title: source.title,
        excerpt: source.excerpt,
        ...(typeof source.dataset_name === "string"
          ? { dataset_name: source.dataset_name }
          : {}),
        ...(typeof source.url === "string"
          ? { url: normalizeUrl(source.url)! }
          : {}),
        ...(typeof source.page === "number" ? { page: source.page } : {}),
      });
    }
  }
  return [...sources.values()];
}

// Uses a non-consuming lookbehind (?<!!) to skip image links (![citation:…])
// without eating the boundary char, so back-to-back citations both match. The
// URL sub-pattern consumes either non-paren chars or a balanced (…) group, so
// disambiguation URLs like .../Foo_(a)_(b) survive rather than truncating at
// the first inner paren.
const CITATION_LINK_RE =
  /(?<!!)\[citation:\s*([^\]]+?)\]\((https?:\/\/(?:[^\s()]|\([^\s()]*\))+)\)/gi;

const GENERIC_CITATION_TITLES = new Set(["source", "来源"]);

export function extractCitationSources(
  markdown: string,
  knowledgeSources: readonly RetrievalSource[] = [],
): CitationSource[] {
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

  const evidenceById = new Map(
    knowledgeSources.map((source) => [source.id, source]),
  );
  for (const match of searchable.matchAll(KNOWLEDGE_REFERENCE_RE)) {
    const reference = match[2]!;
    const evidence = evidenceById.get(
      reference.slice("#knowledge-source-".length),
    );
    if (!evidence) continue;
    const index = match.index ?? 0;
    const existing = sourcesByUrl.get(reference);
    if (existing) {
      existing.count += 1;
      existing.occurrences.push({ index, title: evidence.title });
    } else {
      sourcesByUrl.set(reference, {
        id: reference,
        title: evidence.title,
        url: reference,
        domain: evidence.provider,
        count: 1,
        occurrences: [{ index, title: evidence.title }],
        knowledge: evidence,
      });
    }
  }
  return Array.from(sourcesByUrl.values()).sort(
    (a, b) => a.occurrences[0]!.index - b.occurrences[0]!.index,
  );
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
    if (url.username || url.password) return null;
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

function maskFencedCodeBlocks(markdown: string): string {
  // Match a fenced block up to its matching closing fence, or — while the
  // message is still streaming — to end of input when the fence is unclosed.
  return markdown.replace(
    /(^|\n)(`{3,}|~{3,})[^\n]*(?:\n[\s\S]*?\n\2[^\n]*(?=\n|$)|[\s\S]*$)/g,
    maskKeepingNewlines,
  );
}

function maskInlineCode(markdown: string): string {
  // Only mask closed spans: an unclosed backtick run renders as literal text,
  // so a citation after it is a real, rendered link and must not be masked.
  return markdown.replace(/(`+)[\s\S]*?\1/g, maskKeepingNewlines);
}

function maskKeepingNewlines(block: string): string {
  return block.replace(/[^\n]/g, " ");
}
