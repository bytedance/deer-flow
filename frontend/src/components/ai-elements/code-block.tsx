"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import {
  type ComponentProps,
  createContext,
  type HTMLAttributes,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { type BundledLanguage, codeToHtml, type ShikiTransformer } from "shiki";

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

const lineNumberTransformer: ShikiTransformer = {
  name: "line-numbers",
  line(node, line) {
    node.children.unshift({
      type: "element",
      tagName: "span",
      properties: {
        className: [
          "inline-block",
          "min-w-10",
          "mr-4",
          "text-right",
          "select-none",
          "text-muted-foreground",
        ],
      },
      children: [{ type: "text", value: String(line) }],
    });
  },
};

export async function highlightCode(
  code: string,
  language: BundledLanguage,
  showLineNumbers = false,
) {
  const transformers: ShikiTransformer[] = showLineNumbers
    ? [lineNumberTransformer]
    : [];

  return await Promise.all([
    codeToHtml(code, {
      lang: language,
      theme: "one-light",
      transformers,
    }),
    codeToHtml(code, {
      lang: language,
      theme: "one-dark-pro",
      transformers,
    }),
  ]);
}

export const CodeBlock = ({
  code,
  language,
  showLineNumbers = false,
  className,
  children,
  ...props
}: CodeBlockProps) => {
  const [html, setHtml] = useState<string>("");
  const [darkHtml, setDarkHtml] = useState<string>("");
  const mounted = useRef(false);
  const rawLanguageLabel = String(language || "text");
  const languageLabel = ["bash", "sh", "shell"].includes(rawLanguageLabel)
    ? rawLanguageLabel
    : rawLanguageLabel.replace(/^\w/, (c) => c.toUpperCase());

  useEffect(() => {
    highlightCode(code, language, showLineNumbers).then(([light, dark]) => {
      if (!mounted.current) {
        setHtml(light);
        setDarkHtml(dark);
        mounted.current = true;
      }
    });

    return () => {
      mounted.current = false;
    };
  }, [code, language, showLineNumbers]);

  return (
    <CodeBlockContext.Provider value={{ code }}>
      <div
        className={cn(
          "font-claude-code-body group bg-[var(--code-bg)] text-foreground relative size-full overflow-hidden rounded-xl border border-[var(--code-border)] shadow-[0_10px_30px_-18px_rgba(0,0,0,0.45)]",
          className,
        )}
        data-language={languageLabel}
        {...props}
      >
        <div className="flex items-center justify-between border-b border-[var(--code-border)] bg-[var(--code-header-bg)] px-3 py-0.5 text-[0.7rem] font-medium text-[var(--code-header-fg)]">
          <div className="flex items-center gap-2">
            <span>{languageLabel}</span>
          </div>
          {children && <div className="flex items-center gap-1.5">{children}</div>}
        </div>
        <div className="relative size-full" data-code-body>
          <div
            className="[&>pre]:bg-transparent! [&>pre]:text-foreground! size-full overflow-auto dark:hidden [&_code]:font-mono [&_code]:text-sm [&>pre]:m-0 [&>pre]:px-4 [&>pre]:py-3 [&>pre]:text-sm [&>pre]:whitespace-pre [&>pre]:leading-relaxed"
            // biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
            dangerouslySetInnerHTML={{ __html: html }}
          />
          <div
            className="[&>pre]:bg-transparent! [&>pre]:text-foreground! hidden size-full overflow-auto dark:block [&_code]:font-mono [&_code]:text-sm [&>pre]:m-0 [&>pre]:px-4 [&>pre]:py-3 [&>pre]:text-sm [&>pre]:whitespace-pre [&>pre]:leading-relaxed"
            // biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
            dangerouslySetInnerHTML={{ __html: darkHtml }}
          />
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
