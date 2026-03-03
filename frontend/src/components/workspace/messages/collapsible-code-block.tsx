"use client";

import { ChevronDownIcon } from "lucide-react";
import { useMemo, useState, type HTMLAttributes } from "react";
import { type BundledLanguage } from "shiki";

import {
  CodeBlock,
  CodeBlockCopyButton,
} from "@/components/ai-elements/code-block";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const MAX_LINES_COLLAPSED = 8;

export function CollapsibleCodeBlock({
  children,
  className,
}: HTMLAttributes<HTMLPreElement>) {
  const [isOpen, setIsOpen] = useState(false);

  // Count lines in the code
  const codeContent =
    typeof children === "object" &&
    children &&
    "props" in children &&
    typeof children.props === "object" &&
    children.props &&
    "children" in children.props
      ? String(children.props.children)
      : "";

  const lineCount = useMemo(
    () => (codeContent ? codeContent.split("\n").length : 0),
    [codeContent],
  );
  const shouldShowToggle = lineCount > MAX_LINES_COLLAPSED;
  const language = useMemo(() => {
    if (
      typeof children === "object" &&
      children &&
      "props" in children &&
      typeof children.props === "object" &&
      children.props &&
      "className" in children.props
    ) {
      const className =
        typeof children.props.className === "string"
          ? children.props.className
          : "";
      const match = /language-([a-z0-9-]+)/i.exec(className);
      if (match?.[1]) {
        return match[1] as BundledLanguage;
      }
    }
    return "text" as BundledLanguage;
  }, [children]);

  const codeBlock = (
    <CodeBlock
      code={codeContent}
      language={language}
      className={cn("code-block", className)}
    >
      <div className="flex items-center gap-1.5">
        <CodeBlockCopyButton className="text-muted-foreground hover:text-foreground" />
        {shouldShowToggle && (
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
              aria-label={isOpen ? "Collapse code block" : "Expand code block"}
            >
              <ChevronDownIcon
                className={cn(
                  "size-3.5 transition-transform",
                  isOpen && "rotate-180",
                )}
              />
            </button>
          </CollapsibleTrigger>
        )}
      </div>
    </CodeBlock>
  );

  // If no toggle needed, render normally
  if (!shouldShowToggle) {
    return codeBlock;
  }

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={setIsOpen}
      className="not-prose group/code-block relative"
    >
      <div className="relative">
        <CollapsibleContent
          forceMount
          className={cn(
            "relative overflow-hidden transition-[max-height] duration-300 ease-in-out will-change-[max-height]",
            isOpen ? "max-h-[9999px]" : "max-h-[300px]",
          )}
        >
          {codeBlock}
          {!isOpen && (
            <div className="pointer-events-none absolute right-0 bottom-0 left-0 h-24 bg-gradient-to-t from-[var(--code-bg)] to-transparent" />
          )}
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
