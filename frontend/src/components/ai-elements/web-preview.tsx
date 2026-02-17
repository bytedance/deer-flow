"use client";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { createContext, useContext, useEffect, useState } from "react";

/** Context value shared across all WebPreview compound components. */
export type WebPreviewContextValue = {
  /** The current URL being previewed. */
  url: string;
  /** Updates the preview URL and notifies parent via `onUrlChange`. */
  setUrl: (url: string) => void;
  /** Whether the developer console panel is expanded. */
  consoleOpen: boolean;
  /** Toggles the developer console panel. */
  setConsoleOpen: (open: boolean) => void;
};

const WebPreviewContext = createContext<WebPreviewContextValue | null>(null);

const useWebPreview = () => {
  const context = useContext(WebPreviewContext);
  if (!context) {
    throw new Error("WebPreview components must be used within a WebPreview");
  }
  return context;
};

/** Props for the root WebPreview container that provides context to child components. */
export type WebPreviewProps = ComponentProps<"div"> & {
  /** Initial URL to load when the preview mounts. */
  defaultUrl?: string;
  /** Callback fired whenever the preview URL changes. */
  onUrlChange?: (url: string) => void;
};

/**
 * Root container for the web preview compound component.
 * Provides URL and console state context to all child components.
 */
export const WebPreview = ({
  className,
  children,
  defaultUrl = "",
  onUrlChange,
  ...props
}: WebPreviewProps) => {
  const [url, setUrl] = useState(defaultUrl);
  const [consoleOpen, setConsoleOpen] = useState(false);

  const handleUrlChange = (newUrl: string) => {
    setUrl(newUrl);
    onUrlChange?.(newUrl);
  };

  const contextValue: WebPreviewContextValue = {
    url,
    setUrl: handleUrlChange,
    consoleOpen,
    setConsoleOpen,
  };

  return (
    <WebPreviewContext.Provider value={contextValue}>
      <div
        className={cn(
          "flex size-full flex-col rounded-lg border bg-card",
          className
        )}
        {...props}
      >
        {children}
      </div>
    </WebPreviewContext.Provider>
  );
};

/** Props for the navigation bar displayed above the preview iframe. */
export type WebPreviewNavigationProps = ComponentProps<"div">;

/** Navigation bar containing buttons and the URL input for the preview. */
export const WebPreviewNavigation = ({
  className,
  children,
  ...props
}: WebPreviewNavigationProps) => (
  <div
    className={cn("flex items-center gap-1 border-b p-2", className)}
    {...props}
  >
    {children}
  </div>
);

/** Props for a navigation action button (e.g. back, forward, refresh). */
export type WebPreviewNavigationButtonProps = ComponentProps<typeof Button> & {
  /** Tooltip text shown on hover. */
  tooltip?: string;
};

/** Icon button used in the preview navigation bar with a tooltip. */
export const WebPreviewNavigationButton = ({
  onClick,
  disabled,
  tooltip,
  children,
  ...props
}: WebPreviewNavigationButtonProps) => (
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          className="h-8 w-8 p-0 hover:text-foreground"
          disabled={disabled}
          onClick={onClick}
          size="sm"
          variant="ghost"
          {...props}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        <p>{tooltip}</p>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
);

/** Props for the URL address bar input. */
export type WebPreviewUrlProps = ComponentProps<typeof Input>;

/**
 * URL address bar that syncs with the WebPreview context.
 * Navigates to the entered URL on Enter key press.
 */
export const WebPreviewUrl = ({
  value,
  onChange,
  onKeyDown,
  ...props
}: WebPreviewUrlProps) => {
  const { url, setUrl } = useWebPreview();
  const [inputValue, setInputValue] = useState(url);

  // Sync input value with context URL when it changes externally
  useEffect(() => {
    setInputValue(url);
  }, [url]);

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(event.target.value);
    onChange?.(event);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      const target = event.target as HTMLInputElement;
      setUrl(target.value);
    }
    onKeyDown?.(event);
  };

  return (
    <Input
      className="h-8 flex-1 text-sm"
      onChange={onChange ?? handleChange}
      onKeyDown={handleKeyDown}
      placeholder="Enter URL..."
      value={value ?? inputValue}
      {...props}
    />
  );
};

/** Props for the iframe that renders the previewed content. */
export type WebPreviewBodyProps = ComponentProps<"iframe"> & {
  /** Optional loading indicator displayed while the iframe loads. */
  loading?: ReactNode;
};

/**
 * Sandboxed iframe that displays the preview content.
 * Uses the URL from WebPreview context unless an explicit `src` is provided.
 */
export const WebPreviewBody = ({
  className,
  loading,
  src,
  ...props
}: WebPreviewBodyProps) => {
  const { url } = useWebPreview();

  return (
    <div className="flex-1">
      <iframe
        className={cn("size-full", className)}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-presentation"
        src={(src ?? url) || undefined}
        title="Preview"
        {...props}
      />
      {loading}
    </div>
  );
};

/** Props for the collapsible developer console panel. */
export type WebPreviewConsoleProps = ComponentProps<"div"> & {
  /** Log entries to display, each with a severity level, message, and timestamp. */
  logs?: Array<{
    level: "log" | "warn" | "error";
    message: string;
    timestamp: Date;
  }>;
};

/**
 * Collapsible console panel that displays log output from the previewed page.
 * Logs are color-coded by severity: errors in red, warnings in yellow.
 */
export const WebPreviewConsole = ({
  className,
  logs = [],
  children,
  ...props
}: WebPreviewConsoleProps) => {
  const { consoleOpen, setConsoleOpen } = useWebPreview();

  return (
    <Collapsible
      className={cn("border-t bg-muted/50 font-mono text-sm", className)}
      onOpenChange={setConsoleOpen}
      open={consoleOpen}
      {...props}
    >
      <CollapsibleTrigger asChild>
        <Button
          className="flex w-full items-center justify-between p-4 text-left font-medium hover:bg-muted/50"
          variant="ghost"
        >
          Console
          <ChevronDownIcon
            className={cn(
              "h-4 w-4 transition-transform duration-200",
              consoleOpen && "rotate-180"
            )}
          />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent
        className={cn(
          "px-4 pb-4",
          "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 outline-none data-[state=closed]:animate-out data-[state=open]:animate-in"
        )}
      >
        <div className="max-h-48 space-y-1 overflow-y-auto">
          {logs.length === 0 ? (
            <p className="text-muted-foreground">No console output</p>
          ) : (
            logs.map((log, index) => (
              <div
                className={cn(
                  "text-xs",
                  log.level === "error" && "text-destructive",
                  log.level === "warn" && "text-yellow-600",
                  log.level === "log" && "text-foreground"
                )}
                key={`${log.timestamp.getTime()}-${index}`}
              >
                <span className="text-muted-foreground">
                  {log.timestamp.toLocaleTimeString()}
                </span>{" "}
                {log.message}
              </div>
            ))
          )}
          {children}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
