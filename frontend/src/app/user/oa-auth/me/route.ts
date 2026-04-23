import type { NextRequest } from "next/server";

import {
  getOaAuthSessionCookieName,
  oaAuthRuntimeReady,
} from "@/server/oa-auth/config";
import { getOaAuthSql } from "@/server/oa-auth/db";
import { oaApiError, oaOk } from "@/server/oa-auth/json-response";
import { getUserForActiveSession } from "@/server/oa-auth/repository";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  // #region agent log
  fetch("http://127.0.0.1:7431/ingest/31c75bd3-60da-47c9-bc9e-8ea89535e182", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Debug-Session-Id": "c22be5",
    },
    body: JSON.stringify({
      sessionId: "c22be5",
      runId: "pre-404-debug",
      hypothesisId: "H1",
      location: "user/oa-auth/me/route.ts:GET",
      message: "oa-auth /me handler invoked",
      data: {
        runtimeReady: oaAuthRuntimeReady(),
        hasSessionCookie: Boolean(
          request.cookies.get(getOaAuthSessionCookieName())?.value,
        ),
      },
      timestamp: Date.now(),
    }),
  }).catch(() => {});
  // #endregion
  if (!oaAuthRuntimeReady()) {
    return oaApiError(503, "OA auth is not configured");
  }

  try {
    const sql = await getOaAuthSql();
    const sid = request.cookies.get(getOaAuthSessionCookieName())?.value;
    if (!sid) {
      return oaApiError(401, "unauthorized");
    }
    const user = await getUserForActiveSession(sql, sid);
    if (!user) {
      return oaApiError(401, "unauthorized");
    }
    return oaOk(user);
  } catch (e) {
    console.error("oa-auth me", e);
    return oaApiError(500, "internal error");
  }
}
