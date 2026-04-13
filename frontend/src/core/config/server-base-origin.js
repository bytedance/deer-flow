export function getServerBaseOrigin() {
  const explicitBaseUrl = process.env.BETTER_AUTH_BASE_URL?.trim();
  if (explicitBaseUrl) {
    return explicitBaseUrl.replace(/\/+$/, "");
  }

  const hostname = process.env.HOSTNAME?.trim();
  const port = process.env.PORT?.trim();
  if (hostname && port) {
    return `http://${hostname}:${port}`;
  }

  return "http://localhost:2026";
}
