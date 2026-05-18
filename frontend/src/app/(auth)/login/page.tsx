"use client";

import { LockIcon, MailIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { IndustrialBackdrop } from "@/components/auth/industrial-backdrop";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { parseAuthError } from "@/core/auth/types";
import { setCurrentTenantId } from "@/core/tenant/store";

/**
 * Validate next parameter
 * Prevent open redirect attacks
 * Per RFC-001: Only allow relative paths starting with /
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

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLogin, setIsLogin] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tenantChoices, setTenantChoices] = useState<
    { tenant_id: string; email: string }[]
  >([]);

  const nextParam = searchParams.get("next");
  const redirectPath = validateNextParam(nextParam) ?? "/workspace";

  useEffect(() => {
    if (isAuthenticated) {
      router.push(redirectPath);
    }
  }, [isAuthenticated, redirectPath, router]);

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/v1/auth/setup-status")
      .then((r) => r.json())
      .then((data: { needs_setup?: boolean }) => {
        if (!cancelled && data.needs_setup) {
          router.push("/setup");
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const endpoint = isLogin
        ? "/api/v1/auth/login/local"
        : "/api/v1/auth/register";
      const body = isLogin
        ? `username=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`
        : JSON.stringify({ email, password });
      const headers: HeadersInit = isLogin
        ? { "Content-Type": "application/x-www-form-urlencoded" }
        : { "Content-Type": "application/json" };

      const res = await fetch(endpoint, {
        method: "POST",
        headers,
        body,
        credentials: "include",
      });

      if (!res.ok) {
        const data = await res.json();
        if (
          res.status === 409 &&
          data.detail?.code === "tenant_selection_required"
        ) {
          setTenantChoices(data.detail.tenants);
          setError("");
          return;
        }
        const authError = parseAuthError(data);
        setError(authError.message);
        return;
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
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleTenantSelect = async (tenantId: string) => {
    setLoading(true);
    setError("");

    try {
      const res = await fetch("/api/v1/auth/login/local", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-DeerFlow-Tenant": tenantId,
        },
        body: `username=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`,
        credentials: "include",
      });

      if (res.ok) {
        setTenantChoices([]);
        setCurrentTenantId(tenantId);
        router.push(redirectPath);
      } else {
        const data = await res.json();
        const authError = parseAuthError(data);
        setError(authError.message);
      }
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const subtitle =
    tenantChoices.length > 0
      ? "请选择登录到的组织"
      : isLogin
        ? "登录到设备健康管理工作台"
        : "创建账号以开始使用";

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
              {tenantChoices.length > 0
                ? "选择组织"
                : isLogin
                  ? "欢迎回来"
                  : "新建账号"}
            </h2>
            <p className="text-muted-foreground text-sm">{subtitle}</p>
          </div>

          {tenantChoices.length > 0 ? (
            <div className="space-y-3">
              <p className="text-muted-foreground text-xs">
                你的账号属于多个组织，请选择本次登录的组织。
              </p>
              <div className="space-y-2">
                {tenantChoices.map((t) => (
                  <Button
                    key={t.tenant_id}
                    variant="outline"
                    className="w-full justify-start font-mono text-xs"
                    disabled={loading}
                    onClick={() => handleTenantSelect(t.tenant_id)}
                  >
                    {t.tenant_id}
                  </Button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  setTenantChoices([]);
                  setError("");
                }}
                className="text-muted-foreground hover:text-foreground block w-full text-left text-xs underline-offset-2 transition-colors hover:underline"
              >
                ← 返回登录
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label
                  htmlFor="email"
                  className="text-foreground text-xs font-medium tracking-wide"
                >
                  邮箱
                </label>
                <div className="relative">
                  <MailIcon
                    className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
                    aria-hidden="true"
                  />
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="pl-9"
                    required
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label
                  htmlFor="password"
                  className="text-foreground text-xs font-medium tracking-wide"
                >
                  密码
                </label>
                <div className="relative">
                  <LockIcon
                    className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
                    aria-hidden="true"
                  />
                  <Input
                    id="password"
                    type="password"
                    autoComplete={isLogin ? "current-password" : "new-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="•••••••"
                    className="pl-9"
                    required
                    minLength={isLogin ? 6 : 8}
                  />
                </div>
              </div>

              {error && (
                <p
                  className="text-alarm-high text-xs"
                  role="alert"
                  aria-live="polite"
                >
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "请稍候..." : isLogin ? "登录" : "创建账号"}
              </Button>
            </form>
          )}

          {tenantChoices.length === 0 && (
            <div className="text-muted-foreground text-xs">
              {isLogin ? "还没有账号？" : "已有账号？"}{" "}
              <button
                type="button"
                onClick={() => {
                  setIsLogin(!isLogin);
                  setError("");
                }}
                className="text-primary underline-offset-2 hover:underline"
              >
                {isLogin ? "立即注册" : "去登录"}
              </button>
            </div>
          )}

          <div className="border-border/60 border-t pt-6">
            <Link
              href="/"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs transition-colors"
            >
              ← 返回首页
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
