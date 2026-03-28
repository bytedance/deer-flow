"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

interface AuthConfig {
  feishu: { enabled: boolean };
}

function LoginForm() {
  const searchParams = useSearchParams();
  const redirect = searchParams.get("redirect") ?? "/workspace/chats/new";
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/auth/config")
      .then((res) => res.json())
      .then((data: AuthConfig) => setAuthConfig(data))
      .catch(() => setError("Failed to load auth configuration"));
  }, []);

  const handleFeishuLogin = () => {
    window.location.href = `/api/auth/feishu/login?redirect=${encodeURIComponent(redirect)}`;
  };

  return (
    <div className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-card p-8 shadow-lg">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-foreground">DeerFlow</h1>
        <p className="mt-2 text-sm text-muted-foreground">Sign in to continue</p>
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {authConfig?.feishu?.enabled && (
          <button
            onClick={handleFeishuLogin}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-[#3370ff] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#2860e0]"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path d="M3 7.5L10.5 3L15 10.5L7.5 15L3 7.5Z" fill="white" />
              <path
                d="M10.5 3L21 7.5L15 10.5L10.5 3Z"
                fill="white"
                opacity="0.8"
              />
              <path
                d="M15 10.5L21 7.5L18 21L7.5 15L15 10.5Z"
                fill="white"
                opacity="0.6"
              />
            </svg>
            Sign in with Feishu
          </button>
        )}

        {authConfig && !authConfig.feishu?.enabled && (
          <p className="text-center text-sm text-muted-foreground">
            No authentication providers are configured.
            <br />
            Please enable Feishu auth in config.yaml.
          </p>
        )}

        {!authConfig && !error && (
          <div className="flex justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          </div>
        )}
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Suspense
        fallback={
          <div className="flex justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}
