import { type ClipboardSafeStreamdownProps } from "@/components/ai-elements/streamdown";
import {
  rehypeClobberFragments,
  rehypeSanitizeStep,
  rehypeScopedSlug,
  streamdownPlugins,
} from "@/core/streamdown";

const baseRehypePlugins = streamdownPlugins.rehypePlugins ?? [];

// Insert the scoped slug plugin immediately after the sanitize step: it
// runs after sanitize on purpose (so it also sees headings authored as raw
// HTML once rehypeRaw has parsed them) while PRESERVING sanitize's
// `user-content-` id clobber prefix on the anchors it generates — see
// rehypeScopedSlug. rehypeKatex stays after both so the sanitize schema
// never filters KaTeX's trusted output. If the sanitize entry is ever
// absent, appending the slug plugin last keeps a sane (if less strict)
// chain.
const slugInsertionIndex = (() => {
  const sanitizeIndex = baseRehypePlugins.indexOf(rehypeSanitizeStep);
  const fragmentsIndex = baseRehypePlugins.indexOf(rehypeClobberFragments);
  const after = Math.max(sanitizeIndex, fragmentsIndex);
  return after === -1 ? baseRehypePlugins.length : after + 1;
})();

export const artifactMarkdownPlugins = {
  ...streamdownPlugins,
  rehypePlugins: [
    ...baseRehypePlugins.slice(0, slugInsertionIndex),
    rehypeScopedSlug,
    ...baseRehypePlugins.slice(slugInsertionIndex),
  ] as ClipboardSafeStreamdownProps["rehypePlugins"],
};
