import { cn } from "@/lib/utils";

/** Keep the extension visible when space is tight; the full name stays available. */
export function FileName({
  filename,
  className,
}: {
  filename: string;
  className?: string;
}) {
  const dot = filename.lastIndexOf(".");
  const split = dot > 0 && dot < filename.length - 1;
  return (
    <span title={filename} className={cn("flex min-w-0", className)}>
      <span className="truncate">
        {split ? filename.slice(0, dot) : filename}
      </span>
      {split && <span className="shrink-0">{filename.slice(dot)}</span>}
    </span>
  );
}
