import { EHM_TOKEN_COOKIE } from "./ehm-auth";
import { shouldSuppressAuthErrorRedirect } from "@/core/api/fetcher";
import {
  authErrorMessage,
  buildLoginUrl,
  parseAuthError,
  type AuthErrorCode,
} from "./types";

type ApiErrorLike = {
  status?: number;
  detail?: unknown;
};

export interface ResolvedAuthError {
  code: AuthErrorCode;
  message: string;
  shouldRedirect: boolean;
  shouldClearEhmCookie: boolean;
}

const REDIRECT_CODES = new Set<AuthErrorCode>([
  "token_expired",
  "token_invalid",
  "not_authenticated",
  "user_not_found",
]);

function isApiErrorLike(error: unknown): error is ApiErrorLike {
  return typeof error === "object" && error !== null;
}

function sessionErrorMessage(code: AuthErrorCode, action: string): string {
  if (code === "token_expired") {
    return `登录已过期，请重新登录后再${action}`;
  }
  return `登录状态异常，请重新登录后再${action}`;
}

export function resolveAuthError(
  error: unknown,
  action: string,
): ResolvedAuthError | null {
  if (!isApiErrorLike(error) || error.status !== 401) {
    return null;
  }

  const parsed = parseAuthError(error.detail ?? error);
  if (REDIRECT_CODES.has(parsed.code)) {
    return {
      code: parsed.code,
      message: sessionErrorMessage(parsed.code, action),
      shouldRedirect: true,
      shouldClearEhmCookie:
        parsed.code === "token_expired" || parsed.code === "token_invalid",
    };
  }

  return {
    code: parsed.code,
    message: parsed.message || authErrorMessage(parsed.code),
    shouldRedirect: false,
    shouldClearEhmCookie: false,
  };
}

export function applyResolvedAuthError(
  resolved: ResolvedAuthError,
  pathname: string,
): void {
  if (resolved.shouldClearEhmCookie && typeof document !== "undefined") {
    document.cookie = `${EHM_TOKEN_COOKIE}=; path=/; max-age=0`;
  }

  if (resolved.shouldRedirect && typeof window !== "undefined") {
    if (shouldSuppressAuthErrorRedirect()) {
      return;
    }
    window.setTimeout(() => {
      window.location.href = buildLoginUrl(pathname);
    }, 1500);
  }
}
