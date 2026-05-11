"use client";

import { useCallback, useRef, useState } from "react";

interface CodeBlockProps {
  block: {
    props: {
      code: string;
      language?: string;
      title?: string;
      executable?: boolean;
      filename?: string;
    };
  };
}

function buildSandboxHtml(code: string, language: string): string {
  if (language === "html") {
    return `<!DOCTYPE html><html><body>
      <script>
        const _log = console.log;
        console.log = (...args) => {
          parent.postMessage({type:'sandbox-output', text: args.join(' ')}, '*');
          _log(...args);
        };
        window.onerror = (msg) => {
          parent.postMessage({type:'sandbox-output', text: 'Error: ' + msg}, '*');
        };
      </script>
      ${code}
      <script>parent.postMessage({type:'sandbox-done'}, '*');</script>
    </body></html>`;
  }

  return `<!DOCTYPE html><html><body><script>
    const _log = console.log;
    console.log = (...args) => {
      parent.postMessage({type:'sandbox-output', text: args.join(' ')}, '*');
      _log(...args);
    };
    window.onerror = (msg) => {
      parent.postMessage({type:'sandbox-output', text: 'Error: ' + msg}, '*');
    };
    try {
      ${code}
    } catch(e) {
      parent.postMessage({type:'sandbox-output', text: 'Error: ' + e.message}, '*');
    }
    parent.postMessage({type:'sandbox-done'}, '*');
  </script></body></html>`;
}

// PLACEHOLDER_SANDBOX_RUNNER

function SandboxRunner({ code, language }: { code: string; language: string }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [output, setOutput] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const run = useCallback(() => {
    if (!iframeRef.current) return;
    setRunning(true);
    setOutput(null);

    const html = buildSandboxHtml(code, language);
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    iframeRef.current.src = url;

    const timeout = setTimeout(() => {
      setOutput((prev) => (prev ?? "") + "\n[Execution timed out]");
      setRunning(false);
    }, 10000);

    const handler = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const msg = event.data as { type?: string; text?: string };
      if (msg?.type === "sandbox-output") {
        setOutput((prev) => (prev ? prev + "\n" + msg.text : msg.text ?? ""));
      }
      if (msg?.type === "sandbox-done") {
        setRunning(false);
        clearTimeout(timeout);
        window.removeEventListener("message", handler);
      }
    };
    window.addEventListener("message", handler);

    return () => {
      clearTimeout(timeout);
      window.removeEventListener("message", handler);
      URL.revokeObjectURL(url);
    };
  }, [code, language]);

  return (
    <div className="border-t">
      <div className="flex items-center gap-2 px-4 py-2">
        <button
          onClick={run}
          disabled={running}
          className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          aria-label="Run code"
        >
          {running ? "Running..." : "Run"}
        </button>
      </div>
      {output !== null && (
        <pre className="max-h-40 overflow-auto border-t bg-muted/30 px-4 py-2 text-xs" role="log" aria-label="Execution output">
          {output}
        </pre>
      )}
      <iframe
        ref={iframeRef}
        sandbox="allow-scripts"
        className="hidden"
        title="Code sandbox"
        aria-hidden="true"
      />
    </div>
  );
}

// PLACEHOLDER_MAIN_COMPONENT

export default function CodeBlock({ block }: CodeBlockProps) {
  const { props } = block;
  const { code, language = "text", title, executable, filename } = props;
  const isExecutable = executable && (language === "javascript" || language === "html" || language === "js");

  return (
    <div className="rounded-lg border bg-card" role="region" aria-label={title ?? filename ?? "Code block"}>
      {(title ?? filename) && (
        <div className="flex items-center justify-between border-b px-4 py-2">
          <span className="text-xs font-medium">{title ?? filename}</span>
          {language && (
            <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {language}
            </span>
          )}
        </div>
      )}
      <pre className="overflow-x-auto p-4" aria-label="Code content">
        <code className="text-sm">{code}</code>
      </pre>
      {isExecutable && <SandboxRunner code={code} language={language} />}
    </div>
  );
}
