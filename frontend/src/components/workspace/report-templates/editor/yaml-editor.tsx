"use client";

import { useCallback, useEffect, useRef } from "react";

import { useI18n } from "@/core/i18n/hooks";

interface YamlEditorProps {
  value: string;
  onChange: (value: string) => void;
}

export function YamlEditor({ value, onChange }: YamlEditorProps) {
  const { t } = useI18n();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [value]);

  const handleChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(event.target.value);
    },
    [onChange],
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-3 py-1">
        <span className="text-xs font-medium text-muted-foreground">
          {t.editor.yamlSource}
        </span>
        <span className="text-[10px] text-muted-foreground">
          {value.split("\n").length} {t.editor.lineCountLabel}
        </span>
      </div>
      <div className="flex-1 overflow-auto">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          className="min-h-full w-full resize-none border-0 bg-muted/30 p-3 font-mono text-xs leading-relaxed focus:outline-none focus:ring-0"
          spellCheck={false}
        />
      </div>
    </div>
  );
}
