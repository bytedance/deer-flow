import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  getOaAuthSessionCookieName,
  isOaAuthCookieSecure,
  oaAuthRuntimeReady,
} from "@/server/oa-auth/config";
import { getOaAuthSql } from "@/server/oa-auth/db";
import { oaApiError } from "@/server/oa-auth/json-response";
import { revokeSession } from "@/server/oa-auth/repository";

export const runtime = "nodejs";

export async function POST(_request: NextRequest) {
  if (!oaAuthRuntimeReady()) {
    return oaApiError(503, "OA auth is not configured");
  }

  try {
    const sql = await getOaAuthSql();
    const sid = _request.cookies.get(getOaAuthSessionCookieName())?.value;
    if (sid) {
      await revokeSession(sql, sid);
    }
    const secure = isOaAuthCookieSecure();
    const res = NextResponse.json({
      code: 0,
      message: "logged out",
      data: null,
    });
    res.cookies.set(getOaAuthSessionCookieName(), "", {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      secure,
      maxAge: 0,
    });
    return res;
  } catch (e) {
    console.error("oa-auth logout", e);
    return oaApiError(500, "internal error");
  }
}
