import { randomBytes } from "node:crypto";

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  getOAuthCallbackUrl,
  getOaAuthSessionCookieName,
  isOAuthConfigured,
  isOaAuthCookieSecure,
  isOaAuthDevMode,
  oaAuthRuntimeReady,
} from "@/server/oa-auth/config";
import { getOaAuthSql } from "@/server/oa-auth/db";
import { isLegacyApiAuthCallbackPathname } from "@/server/oa-auth/callback-url";
import { buildAuthorizeUrl } from "@/server/oa-auth/oauth-provider";
import { sanitizePostLoginPath } from "@/server/oa-auth/redirect-path";
import { createSession, getOrCreateDevUser } from "@/server/oa-auth/repository";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  if (!oaAuthRuntimeReady()) {
    return Response.json(
      { error: "OA auth is not configured (database URL + OA_AUTH_DEV_MODE or OAuth env)" },
      { status: 503 },
    );
  }

  try {
    const sql = await getOaAuthSql();
    const redirectPath = sanitizePostLoginPath(
      request.nextUrl.searchParams.get("redirect"),
    );

    if (isOaAuthDevMode()) {
      const user = await getOrCreateDevUser(sql);
      const sess = await createSession(sql, user.id);
      const res = NextResponse.redirect(new URL(redirectPath, request.url), 302);
      const secure = isOaAuthCookieSecure();
      res.cookies.set(getOaAuthSessionCookieName(), sess.id, {
        path: "/",
        httpOnly: true,
        sameSite: "lax",
        secure,
        maxAge: sess.maxAgeSeconds,
      });
      return res;
    }

    if (!isOAuthConfigured()) {
      return Response.json(
        {
          error:
            "OAuth is not configured (OA_OAUTH_CLIENT_ID, OA_OAUTH_CLIENT_SECRET, OA_OAUTH_CALLBACK_URL, OA_OAUTH_BASE_URL)",
        },
        { status: 503 },
      );
    }

    const callbackRaw = getOAuthCallbackUrl();
    let callbackUrl: URL;
    try {
      callbackUrl = new URL(callbackRaw);
    } catch {
      return Response.json(
        {
          error:
            "OA_OAUTH_CALLBACK_URL is not a valid absolute URL; OAuth requires an exact redirect_uri match with the provider console.",
        },
        { status: 503 },
      );
    }
    if (isLegacyApiAuthCallbackPathname(callbackUrl.pathname)) {
      return Response.json(
        {
          error:
            "OA_OAUTH_CALLBACK_URL points to /api/auth/callback (legacy backend path). DeerFlow must use the Next route https://<your-host>/user/oa-auth/callback — register that exact URL in the OAuth app and set OA_OAUTH_CALLBACK_URL to the same string.",
        },
        { status: 503 },
      );
    }

    const state = randomBytes(16).toString("hex");
    const res = NextResponse.redirect(buildAuthorizeUrl(state), 302);
    const secure = isOaAuthCookieSecure();
    res.cookies.set("oauth_state", state, {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: 600,
    });
    res.cookies.set("oa_post_login_redirect", redirectPath, {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: 600,
    });
    return res;
  } catch (e) {
    console.error("oa-auth login", e);
    return Response.json({ error: "login_failed" }, { status: 500 });
  }
}
