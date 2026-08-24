import rehypeSlug from "rehype-slug";

import { type ClipboardSafeStreamdownProps } from "@/components/ai-elements/streamdown";
import { rehypeSanitizeStep, streamdownPlugins } from "@/core/streamdown";

const baseRehypePlugins = streamdownPlugins.rehypePlugins ?? [];

// Insert rehypeSlug immediately after the sanitize step: sanitize clobbers
// `id` values (id="x" → id="user-content-x"), so running the slug plugin
// before it would break the very heading anchors it exists to create, and
// running it before rehypeRaw would miss headings authored as raw HTML.
// rehypeKatex stays after both so the sanitize schema never filters KaTeX's
// trusted output. If the sanitize entry is ever absent, appending the slug
// plugin last keeps a sane (if less strict) chain.
const slugInsertionIndex = (() => {
  const sanitizeIndex = baseRehypePlugins.indexOf(rehypeSanitizeStep);
  return sanitizeIndex === -1 ? baseRehypePlugins.length : sanitizeIndex + 1;
})();

export const artifactMarkdownPlugins = {
  ...streamdownPlugins,
  rehypePlugins: [
    ...baseRehypePlugins.slice(0, slugInsertionIndex),
    rehypeSlug,
    ...baseRehypePlugins.slice(slugInsertionIndex),
  ] as ClipboardSafeStreamdownProps["rehypePlugins"],
};
