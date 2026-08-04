"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AUTH_REQUEST_TIMEOUT_MS } from "@/core/auth/constants";
import { resolveAuthNextPath } from "@/core/auth/next-path";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading",
  );
  const next = resolveAuthNextPath(searchParams.get("next"));

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let redirectTimer: ReturnType<typeof setTimeout> | null = null;
    const requestTimer = setTimeout(
      () => controller.abort(),
      AUTH_REQUEST_TIMEOUT_MS,
    );

    const redirect = (path: string, delay: number) => {
      redirectTimer = setTimeout(() => {
        if (active) {
          router.replace(path);
        }
      }, delay);
    };

    void (async () => {
      try {
        const res = await fetch("/api/v1/auth/me", {
          credentials: "include",
          signal: controller.signal,
        });
        if (!active) return;

        if (res.ok) {
          setStatus("success");
          // Small delay so the user sees the success message
          redirect(next, 300);
        } else {
          setStatus("error");
          redirect("/login?error=sso_failed", 1500);
        }
      } catch {
        if (!active) return;
        setStatus("error");
        redirect("/login?error=sso_failed", 1500);
      } finally {
        clearTimeout(requestTimer);
      }
    })();

    return () => {
      active = false;
      controller.abort();
      clearTimeout(requestTimer);
      if (redirectTimer !== null) {
        clearTimeout(redirectTimer);
      }
    };
  }, [next, router]);

  return (
    <div className="bg-background relative flex min-h-screen items-center justify-center">
      <div className="text-center">
        {status === "loading" && (
          <>
            <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-current border-t-transparent" />
            <p className="text-muted-foreground">Signing you in...</p>
          </>
        )}
        {status === "success" && (
          <p className="text-muted-foreground">Redirecting...</p>
        )}
        {status === "error" && (
          <p className="text-muted-foreground">
            Authentication failed. Redirecting to login...
          </p>
        )}
      </div>
    </div>
  );
}
