const BACKEND_BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "http://127.0.0.1:8001";

export function buildBackendUrl(
  pathname: string,
  requestUrl?: string,
  backendBaseUrl: string = BACKEND_BASE_URL,
) {
  const backendUrl = new URL(pathname, backendBaseUrl);
  if (requestUrl) {
    backendUrl.search = new URL(requestUrl).search;
  }
  return backendUrl;
}
