"use client";

export default function WorkspaceError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex h-full w-full items-center justify-center p-8">
      <div className="max-w-2xl space-y-4">
        <h2 className="text-lg font-semibold">Something went wrong</h2>
        <pre className="max-h-96 overflow-auto rounded-lg bg-black/90 p-4 text-sm leading-relaxed text-red-400 whitespace-pre-wrap break-words">
          {error.message}
          {error.stack && `\n\n${error.stack}`}
          {error.digest && `\n\nDigest: ${error.digest}`}
        </pre>
        <button
          onClick={reset}
          className="bg-muted hover:bg-muted/80 cursor-pointer rounded-md border px-4 py-2 text-sm transition-colors"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
