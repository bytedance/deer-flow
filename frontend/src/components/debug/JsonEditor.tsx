"use client";

interface JsonEditorProps {
  value: string;
  onChange: (value: string) => void;
  error: string | null;
}

export function JsonEditor({ value, onChange, error }: JsonEditorProps) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-2">
        <h3 className="text-sm font-semibold">JSON Props</h3>
      </div>
      <div className="relative flex-1">
        <textarea
          className="h-full w-full resize-none bg-transparent p-4 font-mono text-sm leading-relaxed outline-none"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder='{ "title": "示例", "value": 123 }'
          spellCheck={false}
        />
      </div>
      {error && (
        <div className="border-t border-red-200 bg-red-50 px-4 py-2 dark:border-red-800 dark:bg-red-950">
          <p className="font-mono text-xs text-red-700 dark:text-red-300">
            {error}
          </p>
        </div>
      )}
    </div>
  );
}
