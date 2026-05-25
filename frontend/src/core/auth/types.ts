import { z } from "zod";

// ── User schema (single source of truth) ──────────────────────────

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  system_role: z.enum(["superadmin", "tenant_admin", "user"]),
  tenant_id: z.string().optional().default("default"),
  tenant_name: z.string().optional(),
  user_name: z.string().optional().default(""),
  real_name: z.string().optional().default(""),
});

export type User = z.infer<typeof userSchema>;

// ── SSR auth result (tagged union) ────────────────────────────────

export type AuthResult =
  | { tag: "authenticated"; user: User }
  | { tag: "unauthenticated" }
  | { tag: "gateway_unavailable" }
  | { tag: "config_error"; message: string };

export function assertNever(x: never): never {
  throw new Error(`Unexpected auth result: ${JSON.stringify(x)}`);
}

export function buildLoginUrl(returnPath: string): string {
  return `/login?next=${encodeURIComponent(returnPath)}`;
}

// ── Backend error response parsing ────────────────────────────────

const AUTH_ERROR_CODES = [
  "invalid_credentials",
  "token_expired",
  "token_invalid",
  "user_not_found",
  "provider_not_found",
  "provider_unavailable",
  "not_authenticated",
  "permission_denied",
  "system_already_initialized",
  "tenant_selection_required",
  "tenant_config_error",
  "tenant_not_found",
  "tenant_disabled",
] as const;

export type AuthErrorCode = (typeof AUTH_ERROR_CODES)[number];

const AUTH_ERROR_CATEGORIES = [
  "AUTH_INVALID_TOKEN",
  "AUTH_FORBIDDEN",
  "TENANT_CONFIG_ERROR",
  "AUTH_UPSTREAM_UNAVAILABLE",
] as const;

export type AuthErrorCategory = (typeof AUTH_ERROR_CATEGORIES)[number];

export interface AuthErrorResponse {
  code: AuthErrorCode;
  message: string;
  category?: AuthErrorCategory;
}

const AuthErrorSchema = z.object({
  code: z.enum(AUTH_ERROR_CODES),
  message: z.string(),
  category: z.enum(AUTH_ERROR_CATEGORIES).optional(),
});

const ErrorDetailSchema = z.object({
  msg: z.string(),
  type: z.enum(["value_error"]),
  loc: z.array(z.string()),
});

/**
 * User-facing messages keyed by error code. Falls back to the server's
 * ``message`` field when a code is not listed here.
 */
const AUTH_ERROR_MESSAGES: Record<AuthErrorCode, string> = {
  invalid_credentials: "Invalid credentials. Please check your login details.",
  token_expired: "Your session has expired. Please log in again.",
  token_invalid: "Invalid token. Please re-authenticate.",
  user_not_found: "User account not found.",
  provider_not_found: "Authentication provider is not configured.",
  provider_unavailable: "Authentication service is temporarily unavailable. Please try again later.",
  not_authenticated: "Authentication required. Please log in.",
  permission_denied: "You do not have permission to perform this action.",
  system_already_initialized: "System has already been initialized.",
  tenant_selection_required: "Tenant selection is required.",
  tenant_config_error: "Tenant configuration error. Please contact your administrator.",
  tenant_not_found: "The requested tenant does not exist.",
  tenant_disabled: "This tenant has been disabled. Please contact your administrator.",
};

export function authErrorMessage(code: AuthErrorCode): string {
  return AUTH_ERROR_MESSAGES[code] ?? "An authentication error occurred.";
}

export function parseAuthError(data: unknown): AuthErrorResponse {
  // Try top-level {code, message} first
  const parsed = AuthErrorSchema.safeParse(data);
  if (parsed.success) return parsed.data;

  // Unwrap FastAPI's {detail: {code, message, category?}} envelope
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as Record<string, unknown>).detail;
    const nested = AuthErrorSchema.safeParse(detail);
    if (nested.success) return nested.data;
    // Legacy string-detail responses
    if (typeof detail === "string") {
      return { code: "invalid_credentials", message: detail };
    } else if (Array.isArray(detail)) {
      // Handle list of error details (e.g. from Pydantic validation)
      const firstDetail = detail[0];
      if (typeof firstDetail === "object" && firstDetail !== null) {
        const errorDetail = ErrorDetailSchema.safeParse(firstDetail);
        if (errorDetail.success) {
          return { code: "invalid_credentials", message: errorDetail.data.msg };
        }
      }
    } else if (typeof detail === "object" && detail !== null) {
      const errorDetail = ErrorDetailSchema.safeParse(detail);
      if (errorDetail.success) {
        return { code: "invalid_credentials", message: errorDetail.data.msg };
      }
    }
  }

  return { code: "invalid_credentials", message: "Authentication failed" };
}
