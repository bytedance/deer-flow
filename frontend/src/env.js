import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  /**
   * Specify your server-side environment variables schema here. This way you can ensure the app
   * isn't built with invalid env vars.
   */
  server: {
    GITHUB_OAUTH_TOKEN: z.string().optional(),
    /** Dedicated Postgres URL for OA tables (defaults to DEERFLOW_POSTGRES_URL / DATABASE_URL). */
    OA_AUTH_DATABASE_URL: z.string().url().optional(),
    /** When true, ``GET /user/oa-auth/login`` skips OAuth and signs in a dev user (requires DB). */
    OA_AUTH_DEV_MODE: z.string().optional(),
    /** 与 ``OA_AUTH_DEV_MODE`` 等价，开发环境自动登录。 */
    DEV_MODE: z.string().optional(),
    /** 开发用户邮箱，默认 ``dev@example.com``。 */
    DEV_USER_EMAIL: z.string().optional(),
    OA_AUTH_SESSION_COOKIE_NAME: z.string().optional(),
    OA_AUTH_SESSION_EXPIRY: z.string().optional(),
    OA_AUTH_DEV_USER_EMAIL: z.string().optional(),
    OA_SUPER_ADMIN_EMAIL: z.string().optional(),
    OA_AUTH_COOKIE_SECURE: z.string().optional(),
    OA_OAUTH_CLIENT_ID: z.string().optional(),
    OA_OAUTH_CLIENT_SECRET: z.string().optional(),
    OA_OAUTH_CALLBACK_URL: z.string().url().optional(),
    OA_OAUTH_BASE_URL: z.string().url().optional(),
    DATABASE_URL: z.string().url().optional(),
    DEERFLOW_POSTGRES_URL: z.string().url().optional(),
    NODE_ENV: z
      .enum(["development", "test", "production"])
      .default("development"),
  },

  /**
   * Specify your client-side environment variables schema here. This way you can ensure the app
   * isn't built with invalid env vars. To expose them to the client, prefix them with
   * `NEXT_PUBLIC_`.
   */
  client: {
    NEXT_PUBLIC_BACKEND_BASE_URL: z.string().optional(),
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: z.string().optional(),
    NEXT_PUBLIC_STATIC_WEBSITE_ONLY: z.string().optional(),
    NEXT_PUBLIC_BRAND_NAME: z.string().optional(),
    NEXT_PUBLIC_BRAND_WEBSITE_URL: z.string().url().optional(),
    NEXT_PUBLIC_BRAND_DOCS_URL: z.string().url().optional(),
    NEXT_PUBLIC_BRAND_SUPPORT_EMAIL: z.string().email().optional(),
    /** When true, workspace bootstraps OA / SSO via ``/user/oa-auth/*``. */
    NEXT_PUBLIC_OA_AUTH_ENABLED: z.string().optional(),
    /**
     * When true, ``/workspace`` is open without OA login (local dev / static demos only).
     * Omit or set false so ``/workspace`` requires SSO via ``/user/oa-auth/*``.
     */
    NEXT_PUBLIC_WORKSPACE_AUTH_DISABLED: z.string().optional(),
  },

  /**
   * You can't destruct `process.env` as a regular object in the Next.js edge runtimes (e.g.
   * middlewares) or client-side so we need to destruct manually.
   */
  runtimeEnv: {
    OA_AUTH_DATABASE_URL: process.env.OA_AUTH_DATABASE_URL,
    OA_AUTH_DEV_MODE: process.env.OA_AUTH_DEV_MODE,
    DEV_MODE: process.env.DEV_MODE,
    DEV_USER_EMAIL: process.env.DEV_USER_EMAIL,
    OA_AUTH_SESSION_COOKIE_NAME: process.env.OA_AUTH_SESSION_COOKIE_NAME,
    OA_AUTH_SESSION_EXPIRY: process.env.OA_AUTH_SESSION_EXPIRY,
    OA_AUTH_DEV_USER_EMAIL: process.env.OA_AUTH_DEV_USER_EMAIL,
    OA_SUPER_ADMIN_EMAIL: process.env.OA_SUPER_ADMIN_EMAIL,
    OA_AUTH_COOKIE_SECURE: process.env.OA_AUTH_COOKIE_SECURE,
    OA_OAUTH_CLIENT_ID: process.env.OA_OAUTH_CLIENT_ID,
    OA_OAUTH_CLIENT_SECRET: process.env.OA_OAUTH_CLIENT_SECRET,
    OA_OAUTH_CALLBACK_URL: process.env.OA_OAUTH_CALLBACK_URL,
    OA_OAUTH_BASE_URL: process.env.OA_OAUTH_BASE_URL,
    DATABASE_URL: process.env.DATABASE_URL,
    DEERFLOW_POSTGRES_URL: process.env.DEERFLOW_POSTGRES_URL,
    NODE_ENV: process.env.NODE_ENV,

    NEXT_PUBLIC_BACKEND_BASE_URL: process.env.NEXT_PUBLIC_BACKEND_BASE_URL,
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
    NEXT_PUBLIC_STATIC_WEBSITE_ONLY:
      process.env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY,
    NEXT_PUBLIC_BRAND_NAME: process.env.NEXT_PUBLIC_BRAND_NAME,
    NEXT_PUBLIC_BRAND_WEBSITE_URL: process.env.NEXT_PUBLIC_BRAND_WEBSITE_URL,
    NEXT_PUBLIC_BRAND_DOCS_URL: process.env.NEXT_PUBLIC_BRAND_DOCS_URL,
    NEXT_PUBLIC_BRAND_SUPPORT_EMAIL: process.env.NEXT_PUBLIC_BRAND_SUPPORT_EMAIL,
    NEXT_PUBLIC_OA_AUTH_ENABLED: process.env.NEXT_PUBLIC_OA_AUTH_ENABLED,
    NEXT_PUBLIC_WORKSPACE_AUTH_DISABLED:
      process.env.NEXT_PUBLIC_WORKSPACE_AUTH_DISABLED,
    GITHUB_OAUTH_TOKEN: process.env.GITHUB_OAUTH_TOKEN,
  },
  /**
   * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially
   * useful for Docker builds.
   */
  skipValidation: !!process.env.SKIP_ENV_VALIDATION,
  /**
   * Makes it so that empty strings are treated as undefined. `SOME_VAR: z.string()` and
   * `SOME_VAR=''` will throw an error.
   */
  emptyStringAsUndefined: true,
});
