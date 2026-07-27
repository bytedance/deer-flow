/**
 * Hosts allowed to load Next.js dev-server resources (`/_next/*`,
 * `/__nextjs_font/*`, HMR) from an origin other than the one `pnpm dev` was
 * started on.
 *
 * Next.js answers those requests with 403 unless the host is listed, so a dev
 * stack opened on a LAN address or a proxied hostname serves the SSR HTML but
 * never hydrates: the page renders and nothing on it responds.
 *
 * Dev-only — Next ignores `allowedDevOrigins` in production builds.
 */

/**
 * Reduce one entry to the bare host `allowedDevOrigins` matches against.
 *
 * Next matches on host alone, so an entry that still carries a scheme, port, or
 * path matches nothing and leaves the caller with the same 403 they were trying
 * to fix. Accept the URL people naturally copy out of the address bar.
 *
 * @param {string} value
 * @returns {string} bare host, or `""` if the entry was empty
 */
function normalizeHost(value) {
  let host = value.trim();
  if (!host) return "";

  host = host.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
  host = host.replace(/[/?#].*$/, "");

  const bracketedIpv6 = /^\[([^\]]+)\](?::\d+)?$/.exec(host);
  if (bracketedIpv6) return bracketedIpv6[1];

  // A bare IPv6 literal has several colons and no port to strip; only a single
  // colon can be a `host:port` separator.
  if ((host.match(/:/g) ?? []).length === 1) {
    host = host.replace(/:\d+$/, "");
  }
  return host;
}

/**
 * Parse a comma-separated host list into the shape `allowedDevOrigins` expects.
 *
 * @param {string | undefined} raw
 * @returns {string[]}
 */
export function parseAllowedDevOrigins(raw) {
  return (raw ?? "").split(",").map(normalizeHost).filter(Boolean);
}

/**
 * Read the configured hosts from the environment.
 *
 * @param {Record<string, string | undefined>} [env]
 * @returns {string[]}
 */
export function getAllowedDevOrigins(env = process.env) {
  return parseAllowedDevOrigins(env.DEER_FLOW_DEV_ALLOWED_ORIGINS);
}
