"use client";

import { Button } from "@/components/ui/button";
import { writeTextToClipboard } from "@/core/clipboard";
import { cn } from "@/lib/utils";
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
import type { BundledLanguage } from "shiki";

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

export async function highlightCode(
  code: string,
  language: BundledLanguage,
  showLineNumbers = false,
) {
  const highlighter = await import("./shiki-highlight");
  return await highlighter.highlightCode(code, language, showLineNumbers);
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
  const renderId = useRef(0);

  useEffect(() => {
    const currentRenderId = ++renderId.current;
    setHtml("");
    void highlightCode(code, language, showLineNumbers)
      .then((highlighted) => {
        if (currentRenderId === renderId.current) setHtml(highlighted);
      })
      .catch(() => {
        // The raw-code fallback below remains visible when Shiki cannot load
        // or a model emits an unsupported language identifier.
      });

    return () => {
      renderId.current += 1;
    };
  }, [code, language, showLineNumbers]);

  return (
    <CodeBlockContext.Provider value={{ code }}>
      <div
        className={cn(
          "group bg-background text-foreground relative size-full overflow-hidden rounded-md border",
          className,
        )}
        {...props}
      >
        <div className="relative size-full">
          {html ? (
            <div
              className="[&>pre]:bg-background! [&>pre]:text-foreground! size-full overflow-auto [&_code]:font-mono [&_code]:text-sm [&>pre]:m-0 [&>pre]:text-sm [&>pre]:whitespace-pre-wrap"
              // biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : (
            <pre className="bg-background text-foreground size-full overflow-auto p-4 font-mono text-sm whitespace-pre-wrap">
              <code>{code}</code>
            </pre>
          )}
          {children && (
            <div className="absolute top-2 right-2 flex items-center gap-2">
              {children}
            </div>
          )}
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

  const copyToClipboard = () => {
    void (async () => {
      const didCopy = await writeTextToClipboard(code);
      if (!didCopy) {
        onError?.(new Error("Clipboard API not available"));
        return;
      }

      setIsCopied(true);
      onCopy?.();
      setTimeout(() => setIsCopied(false), timeout);
    })().catch((error) => {
      onError?.(error as Error);
    });
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
