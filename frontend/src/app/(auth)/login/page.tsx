"use client";

import { LockIcon, MailIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useRef } from "react";

import { IndustrialBackdrop } from "@/components/auth/industrial-backdrop";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { setCurrentTenantId } from "@/core/tenant/store";
import { setEhmCookieAndRedirect, isEhmTokenValid } from "@/core/auth/ehm-auth";

/**
 * Validate next parameter
 * Prevent open redirect attacks
 */
function validateNextParam(next: string | null): string | null {
  if (!next) {
    return null;
  }

  if (!next.startsWith("/")) {
    return null;
  }

  if (
    next.startsWith("//") ||
    next.startsWith("http://") ||
    next.startsWith("https://")
  ) {
    return null;
  }

  if (next.includes(":") && !next.startsWith("/")) {
    return null;
  }

  return next;
}

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ehmAutoLogin, setEhmAutoLogin] = useState(false);
  const ehmAttemptedRef = useRef(false);

  const nextParam = searchParams.get("next");
  const redirectPath = validateNextParam(nextParam) ?? "/workspace";

  useEffect(() => {
    if (isAuthenticated) {
      router.push(redirectPath);
    }
  }, [isAuthenticated, redirectPath, router]);

  // EHM token auto-login: set cookie and redirect (no backend call)
  useEffect(() => {
    const ehmToken = searchParams.get("ehm_token");
    if (!ehmToken || ehmAttemptedRef.current || isAuthenticated) return;
    ehmAttemptedRef.current = true;

    if (!isEhmTokenValid(ehmToken)) {
      setError("EHM 单点登录失败：token 无效或已过期");
      const params = new URLSearchParams(searchParams);
      params.delete("ehm_token");
      router.replace(`/login?${params.toString()}`);
      return;
    }

    setEhmAutoLogin(true);
    setLoading(true);

    // Pass user info from EHM (base64-encoded JSON) as cookie
    const ehmUser = searchParams.get("ehm_user") || undefined;

    // Set cookie and redirect — the target page's SSR will read the cookie
    setEhmCookieAndRedirect(ehmToken, redirectPath, ehmUser);
  }, [searchParams, isAuthenticated, redirectPath, router]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch("/api/v1/auth/ins-base/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
        credentials: "include",
      });

      if (!res.ok) {
        const data = await res.json();
        const detail =
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail?.message || data?.message || "登录失败";
        setError(detail);
        return;
      }

      const data = await res.json();
      if (data.tenant_id) {
        setCurrentTenantId(data.tenant_id);
      }

      const meRes = await fetch("/api/v1/auth/me", { credentials: "include" });
      if (meRes.ok) {
        const userData = await meRes.json();
        if (userData.tenant_id) {
          setCurrentTenantId(userData.tenant_id);
        }
      }

      router.push(redirectPath);
    } catch {
      setError("网络错误，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-background grid min-h-screen lg:grid-cols-[3fr_2fr]">
      <IndustrialBackdrop />

      <main className="flex h-screen items-center justify-center px-6 py-12 lg:px-12">
        <div className="w-full max-w-sm space-y-8">
          <div className="space-y-2 lg:hidden">
            <span
              className="bg-primary inline-flex h-8 w-8 items-center justify-center rounded text-sm font-bold text-white"
              aria-hidden="true"
            >
              E
            </span>
            <h1 className="text-foreground text-2xl font-semibold tracking-tight">
              EHM AI 工作台
            </h1>
          </div>

          <div className="space-y-1.5">
            <h2 className="text-foreground text-xl font-semibold tracking-tight">
              欢迎回来
            </h2>
            <p className="text-muted-foreground text-sm">
              登录到设备健康管理工作台
            </p>
          </div>

          {ehmAutoLogin ? (
            <div className="space-y-4">
              <p className="text-muted-foreground text-sm text-center">
                正在通过 EHM 单点登录...
              </p>
            </div>
          ) : (
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-2">
                <label
                  htmlFor="username"
                  className="text-muted-foreground block text-xs font-medium"
                >
                  用户名
                </label>
                <div className="relative">
                  <MailIcon className="text-muted-foreground pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="username"
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="pl-10"
                    placeholder="请输入用户名"
                    required
                  />
                </div>
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="password"
                  className="text-muted-foreground block text-xs font-medium"
                >
                  密码
                </label>
                <div className="relative">
                  <LockIcon className="text-muted-foreground pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10"
                    placeholder="•••••••"
                    required
                  />
                </div>
              </div>

              {error && (
                <p className="text-destructive text-sm">{error}</p>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "登录中..." : "登录"}
              </Button>
            </form>
          )}

          <div className="text-muted-foreground text-center text-xs">
            <Link href="/" className="hover:underline">
              ← 返回首页
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
