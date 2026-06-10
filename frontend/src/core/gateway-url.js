export const DEFAULT_INTERNAL_GATEWAY_URL = "http://127.0.0.1:8001";

/**
 * @param {string | undefined | null} value
 * @returns {boolean}
 */
export function hasConfiguredEnvValue(value) {
  return typeof value === "string" && value.trim().length > 0;
}

/**
 * @param {string} url
 * @returns {string}
 */
export function normalizeGatewayUrl(url) {
  return url.trim().replace(/\/+$/, "");
}

/**
 * @param {{ DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?: string | undefined }} [env]
 * @param {string} [fallbackURL]
 * @returns {string}
 */
export function resolveInternalGatewayUrl(
  env = process.env,
  fallbackURL = DEFAULT_INTERNAL_GATEWAY_URL,
) {
  const configured = env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  return configured && configured.length > 0
    ? normalizeGatewayUrl(configured)
    : normalizeGatewayUrl(fallbackURL);
}
