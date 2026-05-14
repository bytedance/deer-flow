"use client";

import { useState } from "react";

interface ImageBlockProps {
  block: {
    props: {
      src: string;
      alt?: string;
      width?: number;
      height?: number;
      caption?: string;
      fallback?: string;
    };
  };
}

function isValidImageUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

export default function ImageBlock({ block }: ImageBlockProps) {
  const { src, alt, width, height, caption, fallback } = block.props;
  const [error, setError] = useState(false);

  if (!isValidImageUrl(src)) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
        {fallback ?? "Invalid image URL"}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-muted bg-muted/50 p-4 text-sm text-muted-foreground">
        {fallback ?? "Image failed to load"}
      </div>
    );
  }

  return (
    <figure className="my-2 flex flex-col items-start gap-1">
      <img
        src={src}
        alt={alt ?? ""}
        width={width}
        height={height}
        loading="lazy"
        onError={() => setError(true)}
        className="max-w-full rounded-md border"
        style={{
          maxWidth: width ? `${Math.min(width, 800)}px` : "800px",
          maxHeight: height ? `${Math.min(height, 600)}px` : "600px",
        }}
      />
      {caption && (
        <figcaption className="text-xs text-muted-foreground">{caption}</figcaption>
      )}
    </figure>
  );
}
