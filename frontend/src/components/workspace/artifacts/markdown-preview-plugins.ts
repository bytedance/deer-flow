import rehypeSlug from "rehype-slug";

import { type ClipboardSafeStreamdownProps } from "@/components/ai-elements/streamdown";
import { streamdownPlugins } from "@/core/streamdown";

const baseRehypePlugins = streamdownPlugins.rehypePlugins ?? [];

export const artifactMarkdownPlugins = {
  ...streamdownPlugins,
  rehypePlugins: [
    ...baseRehypePlugins.slice(0, 1),
    rehypeSlug,
    ...baseRehypePlugins.slice(1),
  ] as ClipboardSafeStreamdownProps["rehypePlugins"],
};
