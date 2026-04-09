export interface ProxyPolicy {
  /** Allowed upstream path prefixes */
  readonly allowedPaths: readonly string[];
  /** Request headers to strip before forwarding */
  readonly strippedRequestHeaders: ReadonlySet<string>;
  /** Response headers to strip before returning */
  readonly strippedResponseHeaders: ReadonlySet<string>;
  /** Credential mode: which cookie to forward */
  readonly credential: { readonly type: "cookie"; readonly name: string };
  /** Timeout in ms */
  readonly timeoutMs: number;
  /** CSRF: required for non-GET/HEAD */
  readonly csrf: boolean;
}

export const LANGGRAPH_COMPAT_POLICY: ProxyPolicy = {
  allowedPaths: [
    "threads",
    "runs",
    "assistants",
    "store",
    "models",
    "mcp",
    "skills",
    "memory",
  ],
  strippedRequestHeaders: new Set([
    "host",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "authorization",
    "x-api-key",
    "origin",
    "referer",
    "proxy-authorization",
    "proxy-authenticate",
  ]),
  strippedResponseHeaders: new Set([
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "content-length",
    "set-cookie",
  ]),
  credential: { type: "cookie", name: "access_token" },
  timeoutMs: 120_000,
  csrf: true,
};
