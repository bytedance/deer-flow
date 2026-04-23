import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  getOaAuthPublicRedirectOrigin,
  getOaAuthSessionCookieName,
  isOaAuthCookieSecure,
  isOaAuthDevMode,
  oaAuthRuntimeReady,
} from "@/server/oa-auth/config";
import { getOaAuthSql } from "@/server/oa-auth/db";
import { exchangeAuthCode, fetchUserInfo } from "@/server/oa-auth/oauth-provider";
import { sanitizePostLoginPath } from "@/server/oa-auth/redirect-path";
import { createSession, upsertUserFromOAuth } from "@/server/oa-auth/repository";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  if (!oaAuthRuntimeReady()) {
    return Response.json({ code: 503, message: "not configured" }, { status: 503 });
  }
  if (isOaAuthDevMode()) {
    return Response.json(
      { code: 400, message: "OAuth callback is not used in OA_AUTH_DEV_MODE" },
      { status: 400 },
    );
  }

  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  if (!code) {
    return Response.json(
      { code: 400, message: "missing authorization code" },
      { status: 400 },
    );
  }

  const saved = request.cookies.get("oauth_state")?.value;
  const redirectCookie = request.cookies.get("oa_post_login_redirect")?.value;
  if (!saved || !state || saved !== state) {
    return Response.json(
      { code: 403, message: "invalid state parameter" },
      { status: 403 },
    );
  }

  try {
    const sql = await getOaAuthSql();
    const token = await exchangeAuthCode(code);
    const info = await fetchUserInfo(token.access_token, token.openid);
    const user = await upsertUserFromOAuth(sql, info, token.openid);
    const sess = await createSession(sql, user.id);
    const redirectPath = sanitizePostLoginPath(redirectCookie ?? undefined);
    const redirectBase =
      getOaAuthPublicRedirectOrigin() ?? new URL(request.url).origin;
    const res = NextResponse.redirect(new URL(redirectPath, redirectBase), 302);
    const secure = isOaAuthCookieSecure();
    res.cookies.set("oauth_state", "", {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: 0,
    });
    res.cookies.set("oa_post_login_redirect", "", {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: 0,
    });
    res.cookies.set(getOaAuthSessionCookieName(), sess.id, {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: sess.maxAgeSeconds,
    });
    return res;
  } catch (e) {
    console.error("oa-auth callback", e);
    return Response.json(
      { code: 502, message: "SSO authentication failed" },
      { status: 502 },
    );
  }
}
