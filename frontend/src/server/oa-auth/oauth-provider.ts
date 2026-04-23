import {
  getOAuthBaseUrl,
  getOAuthCallbackUrl,
  getOAuthClientId,
  getOAuthClientSecret,
} from "./config";

export type OAuthTokenResponse = {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  openid: string;
};

export type OAuthUserInfo = {
  name: string;
  display_name: string;
  email: string;
  avatar: string;
  dept?: string;
  dept_str?: string;
  gender?: number;
  wx_user_id?: string;
};

export function buildAuthorizeUrl(state: string): string {
  const base = getOAuthBaseUrl();
  const params = new URLSearchParams({
    appid: getOAuthClientId(),
    response_type: "code",
    redirect_uri: getOAuthCallbackUrl(),
    scope: "user_info",
    state,
  });
  return `${base}/oauth2/authorize_new?${params.toString()}`;
}

export async function exchangeAuthCode(
  code: string,
): Promise<OAuthTokenResponse> {
  const base = getOAuthBaseUrl();
  const body = new URLSearchParams({
    code,
    appid: getOAuthClientId(),
    appsecret: getOAuthClientSecret(),
    redirect_uri: getOAuthCallbackUrl(),
    grant_type: "auth_code",
  });

  const res = await fetch(`${base}/api/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  const text = await res.text();
  let json: unknown;
  try {
    json = JSON.parse(text) as unknown;
  } catch {
    throw new Error(`OAuth token response not JSON: ${text.slice(0, 200)}`);
  }

  const o = json as Record<string, unknown>;
  const access_token = o.access_token;
  const openid = o.openid;
  if (typeof access_token !== "string" || !access_token) {
    throw new Error(`OAuth token missing access_token: ${text.slice(0, 200)}`);
  }
  if (typeof openid !== "string" || !openid) {
    throw new Error(`OAuth token missing openid: ${text.slice(0, 200)}`);
  }

  return {
    access_token,
    refresh_token:
      typeof o.refresh_token === "string" ? o.refresh_token : undefined,
    expires_in: typeof o.expires_in === "number" ? o.expires_in : undefined,
    openid,
  };
}

export async function fetchUserInfo(
  accessToken: string,
  openId: string,
): Promise<OAuthUserInfo> {
  const base = getOAuthBaseUrl();
  const body = new URLSearchParams({
    access_token: accessToken,
    appid: getOAuthClientId(),
    openid: openId,
  });

  const res = await fetch(`${base}/user/get_user_info`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  const text = await res.text();
  let json: unknown;
  try {
    json = JSON.parse(text) as unknown;
  } catch {
    throw new Error(`OAuth userinfo not JSON: ${text.slice(0, 200)}`);
  }

  const u = json as Record<string, unknown>;
  const email = u.email;
  if (typeof email !== "string" || !email) {
    throw new Error(`OAuth userinfo missing email: ${text.slice(0, 200)}`);
  }

  return {
    name: typeof u.name === "string" ? u.name : "",
    display_name:
      typeof u.display_name === "string"
        ? u.display_name
        : typeof u.displayName === "string"
          ? u.displayName
          : "",
    email,
    avatar: typeof u.avatar === "string" ? u.avatar : "",
    dept: typeof u.dept === "string" ? u.dept : undefined,
    dept_str:
      typeof u.dept_str === "string"
        ? u.dept_str
        : typeof u.dept === "string"
          ? u.dept
          : "",
    gender: typeof u.gender === "number" ? u.gender : undefined,
    wx_user_id:
      typeof u.wx_user_id === "string"
        ? u.wx_user_id
        : typeof u.wxUserId === "string"
          ? u.wxUserId
          : undefined,
  };
}
