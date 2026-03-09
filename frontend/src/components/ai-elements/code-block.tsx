"use client";

import {
  transformerNotationDiff,
  transformerNotationFocus,
  transformerNotationHighlight,
} from "@shikijs/transformers";
import { CheckIcon, CopyIcon } from "lucide-react";
import {
  type ComponentProps,
  createContext,
  type HTMLAttributes,
  useContext,
  useMemo,
  useState,
} from "react";
import { ShikiHighlighter } from "react-shiki";
import { type BundledLanguage } from "shiki";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type CodeBlockProps = HTMLAttributes<HTMLDivElement> & {
  code: string;
  language: BundledLanguage;
  showLineNumbers?: boolean;
};

type CodeBlockContextType = {
  code: string;
};

const CodeBlockContext = createContext<CodeBlockContextType>({
  code: "",
});

export const CodeBlock = ({
  code,
  language,
  showLineNumbers = false,
  className,
  children,
  ...props
}: CodeBlockProps) => {
  const rawLanguageLabel = String(language || "text");
  const languageLabel = ["bash", "sh", "shell"].includes(rawLanguageLabel)
    ? rawLanguageLabel
    : rawLanguageLabel.replace(/^\w/, (c) => c.toUpperCase());

  const transformers = useMemo(
    () => [
      transformerNotationDiff(),
      transformerNotationHighlight(),
      transformerNotationFocus(),
    ],
    [],
  );

  return (
    <CodeBlockContext.Provider value={{ code }}>
      <div
        className={cn(
          "font-claude-code-body code-block group bg-[var(--code-bg)] text-foreground relative flex flex-col size-full overflow-hidden rounded-xl border border-[var(--code-border)]",
          className,
        )}
        data-language={languageLabel}
        {...props}
      >
        <div className="flex items-center justify-between border-b border-[var(--code-border)] bg-[var(--code-header-bg)] px-3 py-0.5 text-[0.7rem] font-medium text-[var(--code-header-fg)]">
          <div className="flex items-center gap-2">
            <span>{languageLabel}</span>
          </div>
          {children && (
            <div className="flex items-center gap-1.5">{children}</div>
          )}
        </div>
        <div className="relative w-full grow basis-auto min-h-0 overflow-auto" data-code-body>
          <ShikiHighlighter
            as="div"
            language={language}
            theme={{ light: "github-light", dark: "github-dark" }}
            defaultColor="light-dark()"
            showLanguage={false}
            showLineNumbers={showLineNumbers}
            transformers={transformers}
            addDefaultStyles={false}
            className="[&_pre.shiki]:!bg-transparent [&_pre.shiki]:m-0 [&_pre.shiki]:px-4 [&_pre.shiki]:py-3 [&_pre.shiki]:text-sm [&_pre.shiki]:whitespace-pre [&_pre.shiki]:leading-relaxed [&_code]:text-sm [&_code]:font-normal"
          >
            {code}
          </ShikiHighlighter>
        </div>
      </div>
    </CodeBlockContext.Provider>
  );
};

export type CodeBlockCopyButtonProps = ComponentProps<typeof Button> & {
  onCopy?: () => void;
  onError?: (error: Error) => void;
  timeout?: number;
};

export const CodeBlockCopyButton = ({
  onCopy,
  onError,
  timeout = 2000,
  children,
  className,
  ...props
}: CodeBlockCopyButtonProps) => {
  const [isCopied, setIsCopied] = useState(false);
  const { code } = useContext(CodeBlockContext);

  const copyToClipboard = async () => {
    if (typeof window === "undefined" || !navigator?.clipboard?.writeText) {
      onError?.(new Error("Clipboard API not available"));
      return;
    }

    try {
      await navigator.clipboard.writeText(code);
      setIsCopied(true);
      onCopy?.();
      setTimeout(() => setIsCopied(false), timeout);
    } catch (error) {
      onError?.(error as Error);
    }
  };

  const Icon = isCopied ? CheckIcon : CopyIcon;

  return (
    <Button
      className={cn("shrink-0", className)}
      onClick={copyToClipboard}
      size="icon"
      variant="ghost"
      {...props}
    >
      {children ?? <Icon size={14} />}
    </Button>
  );
};
