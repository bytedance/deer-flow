"use client";

import CodeMirror from "@uiw/react-codemirror";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { loadCodeEditorExtensions } from "./code-editor-extensions";
import { useThread } from "./messages/context";

export function CodeEditor({
  className,
  placeholder,
  value,
  readonly,
  disabled,
  autoFocus,
  onChange,
  onSave,
  settings,
  language,
  onSelectionChange,
}: {
  className?: string;
  placeholder?: string;
  value: string;
  readonly?: boolean;
  disabled?: boolean;
  autoFocus?: boolean;
  onChange?: (value: string) => void;
  onSave?: () => void;
  settings?: unknown;
  language?: string;
  onSelectionChange?: (
    selection: {
      from: number;
      to: number;
      rect: { left: number; bottom: number };
    } | null,
  ) => void;
}) {
  const {
    thread: { isLoading },
  } = useThread();
  const { resolvedTheme } = useTheme();
  const [loaded, setLoaded] = useState<
    Awaited<ReturnType<typeof loadCodeEditorExtensions>> | undefined
  >();

  useEffect(() => {
    let cancelled = false;
    setLoaded(undefined);
    void loadCodeEditorExtensions(
      language,
      resolvedTheme === "dark" ? "dark" : "light",
    ).then((extensions) => {
      if (!cancelled) setLoaded(extensions);
    });
    return () => {
      cancelled = true;
    };
  }, [language, resolvedTheme]);

  return (
    <div
      className={cn(
        "flex cursor-text flex-col overflow-hidden rounded-md",
        className,
      )}
      onKeyDown={(event) => {
        if (
          (event.metaKey || event.ctrlKey) &&
          event.key.toLowerCase() === "s"
        ) {
          event.preventDefault();
          onSave?.();
        }
      }}
    >
      {isLoading || !loaded ? (
        <Textarea
          className={cn(
            "h-full overflow-auto font-mono [&_.cm-editor]:h-full [&_.cm-focused]:outline-none!",
            "resize-none p-4! [&_.cm-line]:px-2! [&_.cm-line]:py-0!",
            "border-none",
          )}
          readOnly
          value={value}
        />
      ) : (
        <CodeMirror
          // Keep the source focusable for keyboard selection. readOnly below
          // still prevents edits until the user explicitly enters edit mode.
          editable={
            disabled !== true &&
            (readonly !== true || onSelectionChange !== undefined)
          }
          readOnly={readonly === true || disabled === true}
          placeholder={placeholder}
          className={cn(
            "h-full overflow-auto font-mono [&_.cm-editor]:h-full [&_.cm-focused]:outline-none!",
            "px-2 py-0! [&_.cm-line]:px-2! [&_.cm-line]:py-0!",
          )}
          theme={loaded.theme}
          extensions={loaded.extensions}
          basicSetup={{
            foldGutter:
              (settings as { foldGutter?: boolean })?.foldGutter ?? false,
            highlightActiveLine: false,
            highlightActiveLineGutter: false,
            lineNumbers:
              (settings as { lineNumbers?: boolean })?.lineNumbers ?? false,
          }}
          autoFocus={autoFocus}
          onChange={onChange}
          onUpdate={(update) => {
            if (
              !onSelectionChange ||
              (!update.selectionSet && !update.docChanged)
            )
              return;
            const range = update.state.selection.main;
            const rect = update.view.coordsAtPos(range.to);
            onSelectionChange(
              !update.docChanged &&
                !range.empty &&
                update.state.selection.ranges.length === 1 &&
                rect
                ? { from: range.from, to: range.to, rect }
                : null,
            );
          }}
          value={value}
        />
      )}
    </div>
  );
}
