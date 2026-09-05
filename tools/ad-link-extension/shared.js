export const DEFAULT_SETTINGS = {
  apiBaseUrl: "http://localhost:8001",
  affiliateId: "",
  enabled: false,
  excludedDomains: [],
  excludedUrls: []
};

export async function getSettings() {
  const stored = await chrome.storage.local.get(DEFAULT_SETTINGS);
  return {
    ...DEFAULT_SETTINGS,
    ...stored,
    excludedDomains: Array.isArray(stored.excludedDomains) ? stored.excludedDomains : [],
    excludedUrls: Array.isArray(stored.excludedUrls) ? stored.excludedUrls : []
  };
}

export function isEligibleUrl(rawUrl, pageUrl, settings) {
  let target;
  let page;
  try {
    target = new URL(rawUrl, pageUrl);
    page = new URL(pageUrl);
  } catch {
    return false;
  }

  if (!["http:", "https:"].includes(target.protocol)) return false;
  if (target.hostname === "vbtrax.com" || target.hostname.endsWith(".vbtrax.com")) return false;
  if (target.hostname === page.hostname && target.href === page.href) return false;
  if (settings.excludedDomains.some((domain) => target.hostname === domain || target.hostname.endsWith(`.${domain}`))) {
    return false;
  }
  if (settings.excludedUrls.some((url) => target.href === url)) return false;
  return true;
}
