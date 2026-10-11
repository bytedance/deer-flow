import type { CSSProperties, ImgHTMLAttributes } from "react";

import { resolveMessageImageURL } from "@/core/artifacts/utils";
import { cn } from "@/lib/utils";

/**
 * Custom image component that handles artifact URLs
 */
export function MessageImage({
  src,
  alt,
  threadId,
  artifactPaths,
  maxWidth = "90%",
  ...props
}: ImgHTMLAttributes<HTMLImageElement> & {
  threadId: string;
  artifactPaths: readonly string[];
  maxWidth?: string;
}) {
  if (!src) return null;

  // `maxWidth` is applied inline rather than through a `max-w-[${maxWidth}]`
  // class: Tailwind's JIT only generates utilities it can find as literal
  // source tokens, so an interpolated arbitrary value would never be emitted.
  const imgClassName = cn("overflow-hidden rounded-lg", props.className);
  const imgStyle: CSSProperties = { maxWidth, ...props.style };

  if (typeof src !== "string") {
    return (
      <img
        {...props}
        className={imgClassName}
        style={imgStyle}
        src={src}
        alt={alt}
        loading="lazy"
        decoding="async"
      />
    );
  }

  const url = resolveMessageImageURL(src, threadId, artifactPaths);

  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      <img
        {...props}
        className={imgClassName}
        style={imgStyle}
        src={url}
        alt={alt}
        loading="lazy"
        decoding="async"
      />
    </a>
  );
}
