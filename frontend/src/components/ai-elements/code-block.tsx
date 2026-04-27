"use client";

import { Button } from "@/components/ui/button";
import { highlightInWorker } from "@/core/shiki/client";
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
import { type BundledLanguage } from "shiki";

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
  const [html, setHtml] = useState<string>("");
  const [darkHtml, setDarkHtml] = useState<string>("");
  // Monotonic counter of highlight requests dispatched from this block.
  // When streaming updates `code` every token, only the most recent request
  // is allowed to write state — older in-flight responses from the worker
  // are ignored so the final HTML always reflects the latest code value.
  const latestGeneration = useRef(0);

  useEffect(() => {
    const generation = ++latestGeneration.current;
    let cancelled = false;

    highlightInWorker(code, language, showLineNumbers)
      .then(([light, dark]) => {
        if (cancelled || generation !== latestGeneration.current) {
          return;
        }
        setHtml(light);
        setDarkHtml(dark);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        // A highlight failure must not blank the code block — keep whatever
        // HTML we already rendered and surface the error in the console so
        // it's discoverable without breaking the conversation view.
        // eslint-disable-next-line no-console
        console.error("Shiki highlight failed:", err);
      });

    return () => {
      cancelled = true;
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
          <div
            className="[&>pre]:bg-background! [&>pre]:text-foreground! size-full overflow-auto dark:hidden [&_code]:font-mono [&_code]:text-sm [&>pre]:m-0 [&>pre]:text-sm [&>pre]:whitespace-pre-wrap"
            // biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
            dangerouslySetInnerHTML={{ __html: html }}
          />
          <div
            className="[&>pre]:bg-background! [&>pre]:text-foreground! hidden size-full overflow-auto dark:block [&_code]:font-mono [&_code]:text-sm [&>pre]:m-0 [&>pre]:text-sm [&>pre]:whitespace-pre-wrap"
            // biome-ignore lint/security/noDangerouslySetInnerHtml: "this is needed."
            dangerouslySetInnerHTML={{ __html: darkHtml }}
          />
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
