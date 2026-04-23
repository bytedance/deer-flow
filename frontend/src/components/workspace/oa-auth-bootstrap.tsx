"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { setGatewayUserIdOverride } from "@/core/api/gateway-fetch";
import {
  type OaAuthUser,
  fetchOaAuthMeSilently,
  getCurrentPath,
  getOaAuthLoginURL,
} from "@/core/auth/oa-auth";
import { OaAuthUserProvider } from "@/core/auth/oa-auth-user-context";
import { setWorkspaceLoginRequired } from "@/core/auth/workspace-login-gate";

type Phase = "config" | "ready" | "error";

export function OaAuthBootstrap({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("config");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [oaUser, setOaUser] = useState<OaAuthUser | null>(null);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const confRes = await fetch("/user/workspace-auth/config");
        if (!confRes.ok) {
          throw new Error(`config ${confRes.status}`);
        }
        const conf = (await confRes.json()) as {
          workspaceLoginRequired?: boolean;
          oaAuthConfigured?: boolean;
        };
        const required = conf.workspaceLoginRequired !== false;
        if (cancelled) return;
        setWorkspaceLoginRequired(required);

        if (!required) {
          setOaUser(null);
          setPhase("ready");
          return;
        }

        if (!conf.oaAuthConfigured) {
          setErrorMessage(
            "登录模块未就绪：请在服务端配置 Postgres（DEERFLOW_POSTGRES_URL / OA_AUTH_DATABASE_URL），并启用 DEV_MODE=true（或 OA_AUTH_DEV_MODE=true）以自动注入 DEV_USER_EMAIL（默认 dev@example.com），或配置 OAuth（OA_OAUTH_CLIENT_ID、OA_OAUTH_CLIENT_SECRET、OA_OAUTH_CALLBACK_URL、OA_OAUTH_BASE_URL）。不需要登录时可设置 NEXT_PUBLIC_WORKSPACE_AUTH_DISABLED=true。",
          );
          setPhase("error");
          return;
        }

        try {
          const user = await fetchOaAuthMeSilently();
          if (cancelled) return;
          setGatewayUserIdOverride(user.id);
          setOaUser(user);
          setPhase("ready");
        } catch (e: unknown) {
          if (cancelled) return;
          const status =
            typeof e === "object" && e !== null && "status" in e
              ? (e as { status?: number }).status
              : undefined;
          if (status === 401) {
            window.location.href = getOaAuthLoginURL(getCurrentPath());
            return;
          }
          if (status === 503) {
            setErrorMessage(
              "登录服务不可用（HTTP 503）。请确认数据库可连且 OA 环境变量完整；不需要登录时可设置 NEXT_PUBLIC_WORKSPACE_AUTH_DISABLED=true。",
            );
            setPhase("error");
            return;
          }
          setErrorMessage(
            status != null
              ? `登录校验失败（HTTP ${status}）。请稍后重试或联系管理员。`
              : "登录校验失败。请检查网络后重试。",
          );
          setPhase("error");
        }
      } catch {
        if (cancelled) return;
        setErrorMessage("无法读取登录策略配置，请刷新页面重试。");
        setPhase("error");
      }
    })();

    return () => {
      cancelled = true;
      setWorkspaceLoginRequired(false);
      setOaUser(null);
    };
  }, []);

  if (phase === "config") {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        正在验证登录状态…
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
        <p className="max-w-lg text-sm text-muted-foreground">
          {errorMessage ?? "无法完成登录校验。"}
        </p>
        <button
          type="button"
          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          onClick={() => {
            window.location.reload();
          }}
        >
          重新加载
        </button>
      </div>
    );
  }

  return <OaAuthUserProvider value={oaUser}>{children}</OaAuthUserProvider>;
}
