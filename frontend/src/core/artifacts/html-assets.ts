import { appendHtmlPreviewBaseHref } from "./preview";

const MAX_RESOURCES = 32;
const MAX_RESOURCE_BYTES = 4 * 1024 * 1024;
const MAX_TOTAL_BYTES = 16 * 1024 * 1024;
const MAX_CSS_DEPTH = 8;
const MAX_INLINE_BYTES = 24 * 1024 * 1024;
const EMPTY_RESOURCE = "data:,";

/** Locate CSS URL tokens without treating comments or ordinary strings as URLs. */
async function rewriteCss(
  css: string,
  replace: (value: string, stylesheet: boolean) => Promise<string>,
) {
  const quoteUrl = (value: string) =>
    `"${value
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/[\r\n\f]/g, "\\A ")}"`;
  const tokens = /\/\*|["']|\burl\s*\(|@import\s+/gi;
  let result = "";
  let copied = 0;
  let match: RegExpExecArray | null;
  const stringEnd = (start: number, quote: string) => {
    let end = start;
    for (; end < css.length; end++) {
      if (css[end] === "\\") end++;
      else if (css[end] === quote) break;
    }
    return end;
  };
  while ((match = tokens.exec(css))) {
    const token = match[0];
    if (token === "/*") {
      const end = css.indexOf("*/", tokens.lastIndex);
      tokens.lastIndex = end < 0 ? css.length : end + 2;
      continue;
    }
    if (token === '"' || token === "'") {
      tokens.lastIndex = stringEnd(tokens.lastIndex, token) + 1;
      continue;
    }
    const imported = token.toLowerCase().startsWith("@import");
    let start = tokens.lastIndex;
    while (/\s/.test(css[start] ?? "")) start++;
    if (imported && css.slice(start, start + 3).toLowerCase() === "url") {
      const opening = /^url\s*\(/i.exec(css.slice(start));
      if (!opening) continue;
      start += opening[0].length;
      while (/\s/.test(css[start] ?? "")) start++;
    } else if (imported && css[start] !== '"' && css[start] !== "'") {
      continue;
    }
    const quote = css[start] === '"' || css[start] === "'" ? css[start]! : null;
    const valueStart = quote ? start + 1 : start;
    let end = quote ? stringEnd(valueStart, quote) : valueStart;
    if (!quote) {
      for (; end < css.length; end++) {
        if (css[end] === "\\") end++;
        else if (css[end] === ")") break;
      }
    }
    if (end >= css.length) break;
    const raw = css.slice(valueStart, end);
    const encoded = quote ? raw : raw.trim();
    const value = encoded.replace(
      /\\([0-9a-f]{1,6}\s?|\r\n|[\n\r\f]|.)/gi,
      (_escape, escaped: string) => {
        if (/^[0-9a-f]/i.test(escaped)) {
          const code = Number.parseInt(escaped.trim(), 16);
          return String.fromCodePoint(
            code === 0 || code > 0x10ffff ? 0xfffd : code,
          );
        }
        return /^[\n\r\f]/.test(escaped) ? "" : escaped;
      },
    );
    const replacement = await replace(value, imported);
    const formattedReplacement =
      replacement === value || quote
        ? replacement === value
          ? raw
          : replacement
        : quoteUrl(replacement);
    result += css.slice(copied, valueStart) + formattedReplacement;
    copied = end;
    tokens.lastIndex = end + (quote ? 1 : 0);
  }
  return result + css.slice(copied);
}

/** Follow srcset URL boundaries, including commas within data URLs. */
async function rewriteSrcset(
  value: string,
  replace: (url: string) => Promise<string>,
) {
  let result = "";
  let copied = 0;
  let position = 0;
  while (position < value.length) {
    while (/[\s,]/.test(value[position] ?? "")) position++;
    const start = position;
    while (position < value.length && !/\s/.test(value[position]!)) position++;
    let end = position;
    while (value[end - 1] === ",") end--;
    if (end > start) {
      result +=
        value.slice(copied, start) + (await replace(value.slice(start, end)));
      copied = end;
    }
    if (end < position) continue;
    let parentheses = 0;
    while (position < value.length) {
      const character = value[position++];
      if (character === "(") parentheses++;
      if (character === ")") parentheses--;
      if (character === "," && parentheses === 0) break;
    }
  }
  return result + value.slice(copied);
}

/**
 * Load only this thread's artifact resources with the parent's session. The
 * sandbox remains opaque; data URLs work across that origin boundary whereas
 * parent-owned Blob URLs are blocked by Chromium's storage partition checks.
 */
export async function prepareHtmlPreview(
  content: string,
  artifactUrl?: string,
  signal?: AbortSignal,
): Promise<{ content: string; failedResources: number }> {
  const unchanged = {
    content: appendHtmlPreviewBaseHref(content, artifactUrl),
    failedResources: 0,
  };
  if (!artifactUrl) return unchanged;
  const source = new URL(artifactUrl, window.location.href);
  const route = /^(.*\/api\/threads\/[^/]+\/artifacts\/)/.exec(
    source.pathname,
  )?.[1];
  // Public demos and non-thread document previews retain their existing path.
  if (!route || !["http:", "https:"].includes(source.protocol))
    return unchanged;

  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  const resources = new Map<string, string>();
  const loading = new Set<string>();
  let totalBytes = 0;
  let failedResources = 0;
  let inlineBytes = 0;

  function inline(value: string) {
    inlineBytes += value.length;
    if (inlineBytes > MAX_INLINE_BYTES) {
      failedResources++;
      return EMPTY_RESOURCE;
    }
    return value;
  }

  function localUrl(value: string, base: string) {
    if (!value || value.startsWith("#")) return null;
    const target = new URL(value, base);
    if (target.origin !== source.origin || !target.pathname.startsWith(route!))
      return null;
    if (target.username || target.password) return null;
    try {
      if (
        target.pathname
          .slice(route!.length)
          .split("/")
          .some((segment) => /[/\\\u0000]/.test(decodeURIComponent(segment)))
      )
        return null;
    } catch {
      return null;
    }
    return target;
  }

  async function resource(
    value: string,
    base: string,
    stylesheet = false,
    depth = 0,
    resolveRelative = false,
    integrity?: string,
  ): Promise<string> {
    if (!value || value.startsWith("#")) return value;
    let target: URL | null;
    try {
      target = localUrl(value, base);
    } catch {
      return value;
    }
    if (!target) {
      // An inlined stylesheet has no original URL of its own. Keep resources
      // outside the allowed route browser-loaded at their original location.
      return resolveRelative ? new URL(value, base).href : value;
    }
    const fragment = target.hash;
    target.hash = "";
    const key = `${stylesheet ? "css:" : "asset:"}${target.href}:${integrity ?? ""}`;
    const cached = resources.get(key);
    if (cached !== undefined)
      return inline(cached + (cached === EMPTY_RESOURCE ? "" : fragment));
    if (
      loading.has(key) ||
      resources.size + loading.size >= MAX_RESOURCES ||
      totalBytes >= MAX_TOTAL_BYTES ||
      inlineBytes >= MAX_INLINE_BYTES ||
      controller.signal.aborted ||
      depth > MAX_CSS_DEPTH
    ) {
      failedResources++;
      return EMPTY_RESOURCE;
    }
    loading.add(key);
    try {
      controller.signal.throwIfAborted();
      // A failed optional asset must not trigger the API client's page-wide
      // login redirect. The top-level document load keeps that auth policy.
      const response = await globalThis.fetch(target.href, {
        credentials: "include",
        signal: controller.signal,
        redirect: "error",
        ...(integrity ? { integrity } : {}),
      });
      if (!response.ok || !response.body)
        throw new Error("Artifact resource unavailable");
      const reader = response.body.getReader();
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      let bytes = 0;
      try {
        while (true) {
          const { done, value: chunk } = await reader.read();
          if (done) break;
          bytes += chunk.byteLength;
          totalBytes += chunk.byteLength;
          if (bytes > MAX_RESOURCE_BYTES || totalBytes > MAX_TOTAL_BYTES)
            throw new Error("Artifact preview resource limit exceeded");
          chunks.push(new Uint8Array(chunk));
        }
      } finally {
        await reader.cancel().catch(() => undefined);
      }
      let blob = new Blob(chunks, {
        type:
          response.headers.get("Content-Type") ?? "application/octet-stream",
      });
      if (stylesheet) {
        const css = await rewriteCss(await blob.text(), (reference, imported) =>
          resource(reference, target.href, imported, depth + 1, true),
        );
        blob = new Blob([css], { type: "text/css;charset=utf-8" });
      }
      controller.signal.throwIfAborted();
      const encodedBytes = new Uint8Array(await blob.arrayBuffer());
      let binary = "";
      for (let start = 0; start < encodedBytes.length; start += 0x8000) {
        binary += String.fromCharCode(
          ...encodedBytes.subarray(start, start + 0x8000),
        );
      }
      const url = `data:${blob.type};base64,${btoa(binary)}`;
      resources.set(key, url);
      return inline(url + fragment);
    } catch (error) {
      if (signal?.aborted) throw error;
      failedResources++;
      resources.set(key, EMPTY_RESOURCE);
      return EMPTY_RESOURCE;
    } finally {
      loading.delete(key);
    }
  }

  try {
    const document = new DOMParser().parseFromString(content, "text/html");
    const base = new URL(
      document.querySelector("base[href]")?.getAttribute("href") ?? source.href,
      source.href,
    ).href;
    for (const element of document.querySelectorAll(
      "[src], [srcset], [poster], link[href], style, [style]",
    )) {
      for (const attribute of ["src", "poster"]) {
        const value = element.getAttribute(attribute);
        if (value && element.tagName !== "IFRAME") {
          const rewritten = await resource(
            value,
            base,
            false,
            0,
            false,
            element.getAttribute("integrity") ?? undefined,
          );
          element.setAttribute(attribute, rewritten);
          if (rewritten !== value) element.removeAttribute("integrity");
        }
      }
      const srcset = element.getAttribute("srcset");
      if (srcset)
        element.setAttribute(
          "srcset",
          await rewriteSrcset(srcset, (reference) => resource(reference, base)),
        );
      if (
        element.tagName === "LINK" &&
        element
          .getAttribute("rel")
          ?.toLowerCase()
          .split(/\s+/)
          .includes("stylesheet")
      ) {
        const value = element.getAttribute("href");
        if (value) {
          const rewritten = await resource(
            value,
            base,
            true,
            0,
            false,
            element.getAttribute("integrity") ?? undefined,
          );
          element.setAttribute("href", rewritten);
          // Fetch checked the original bytes. Rewritten CSS has a new hash.
          if (rewritten !== value) element.removeAttribute("integrity");
        }
      }
      if (element.localName === "style")
        element.textContent = await rewriteCss(
          element.textContent ?? "",
          (reference, imported) => resource(reference, base, imported),
        );
      const style = element.getAttribute("style");
      if (style)
        element.setAttribute(
          "style",
          await rewriteCss(style, (reference, imported) =>
            resource(reference, base, imported),
          ),
        );
    }
    signal?.throwIfAborted();
    return {
      content: appendHtmlPreviewBaseHref(
        Array.from(document.childNodes, (node) =>
          node === document.documentElement
            ? document.documentElement.outerHTML
            : new XMLSerializer().serializeToString(node),
        ).join(""),
        artifactUrl,
      ),
      failedResources,
    };
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
