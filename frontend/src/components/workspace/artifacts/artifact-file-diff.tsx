import {
  GitCompareArrowsIcon,
  PencilLineIcon,
  PlusIcon,
  MinusIcon,
} from "lucide-react";
import { useMemo } from "react";

import { buildThreadFileDiff } from "@/core/artifacts/diff";
import { cn } from "@/lib/utils";

export function ArtifactFileDiff({
  afterContent,
  afterLabel,
  beforeContent,
  beforeLabel,
  title,
}: {
  afterContent: string;
  afterLabel: string;
  beforeContent: string;
  beforeLabel: string;
  title: string;
}) {
  const diff = useMemo(() => {
    return buildThreadFileDiff({
      beforeContent,
      afterContent,
    });
  }, [afterContent, beforeContent]);

  return (
    <div className="size-full overflow-auto font-mono text-sm">
      <div className="bg-background/95 sticky top-0 z-10 border-b backdrop-blur-sm">
        <div className="flex items-center justify-between gap-4 px-4 py-2">
          <div className="text-muted-foreground flex items-center gap-2 text-xs font-medium">
            <GitCompareArrowsIcon className="size-4" />
            <span>{title}</span>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1 text-green-600">
              <PlusIcon className="size-3" />
              {diff.summary.added}
            </span>
            <span className="flex items-center gap-1 text-red-600">
              <MinusIcon className="size-3" />
              {diff.summary.removed}
            </span>
            <span className="flex items-center gap-1 text-amber-600">
              <PencilLineIcon className="size-3" />
              {diff.summary.modified}
            </span>
          </div>
        </div>
        <div className="grid min-w-max grid-cols-2 border-t text-xs font-medium">
          <div className="text-muted-foreground border-r px-4 py-2">
            {beforeLabel}
          </div>
          <div className="text-muted-foreground px-4 py-2">{afterLabel}</div>
        </div>
      </div>
      <div className="min-w-max">
        {diff.lines.map((line, index) => (
          <div key={`${line.kind}-${index}`} className="grid grid-cols-2">
            <DiffCell
              className="border-r"
              content={line.beforeContent}
              kind={line.kind}
              lineNumber={line.beforeLineNumber}
              side="before"
            />
            <DiffCell
              content={line.afterContent}
              kind={line.kind}
              lineNumber={line.afterLineNumber}
              side="after"
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function DiffCell({
  className,
  content,
  kind,
  lineNumber,
  side,
}: {
  className?: string;
  content: string;
  kind: "context" | "added" | "removed" | "modified";
  lineNumber: number | null;
  side: "before" | "after";
}) {
  const isHighlighted =
    kind === "modified" ||
    (kind === "removed" && side === "before") ||
    (kind === "added" && side === "after");
  const tone =
    kind === "modified"
      ? side === "before"
        ? "bg-red-500/8"
        : "bg-green-500/8"
      : kind === "removed"
        ? side === "before"
          ? "bg-red-500/8"
          : ""
        : kind === "added"
          ? side === "after"
            ? "bg-green-500/8"
            : ""
          : "";

  return (
    <div
      className={cn(
        "grid min-h-7 grid-cols-[3.5rem_minmax(0,1fr)] border-b",
        tone,
        className,
      )}
    >
      <div
        className={cn(
          "text-muted-foreground border-r px-2 py-1 text-right text-xs select-none",
          isHighlighted && side === "before" && "text-red-600",
          isHighlighted && side === "after" && "text-green-600",
        )}
      >
        {lineNumber ?? ""}
      </div>
      <pre className="m-0 overflow-x-auto px-3 py-1 whitespace-pre">
        {content || " "}
      </pre>
    </div>
  );
}
