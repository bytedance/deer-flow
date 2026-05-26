"use client";

export default function EditorError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
      <h2 className="text-lg font-semibold">Something went wrong</h2>
      <p className="max-w-md text-center text-sm text-muted-foreground">
        {error.message || "The template editor encountered an unexpected error."}
      </p>
      <button
        type="button"
        onClick={reset}
        className="rounded border px-4 py-1.5 text-sm hover:bg-accent"
      >
        Try again
      </button>
    </div>
  );
}
