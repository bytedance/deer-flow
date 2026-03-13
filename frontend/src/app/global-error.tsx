"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html>
      <body
        style={{
          fontFamily: "system-ui, -apple-system, sans-serif",
          padding: "2rem",
          maxWidth: "720px",
          margin: "0 auto",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>
          Something went wrong
        </h1>
        <pre
          style={{
            background: "#1a1a1a",
            color: "#f87171",
            padding: "1rem",
            borderRadius: "8px",
            overflow: "auto",
            fontSize: "0.85rem",
            lineHeight: 1.5,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {error.message}
          {error.stack && `\n\n${error.stack}`}
          {error.digest && `\n\nDigest: ${error.digest}`}
        </pre>
        <button
          onClick={reset}
          style={{
            marginTop: "1rem",
            padding: "0.5rem 1rem",
            borderRadius: "6px",
            border: "1px solid #555",
            background: "#2a2a2a",
            color: "#fff",
            cursor: "pointer",
            fontSize: "0.875rem",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
