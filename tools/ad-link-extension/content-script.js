const processed = new WeakSet();
const MAX_LINKS_PER_PAGE = 50;
let settings;

void initialize();

async function initialize() {
  settings = await getSettings();
  if (!settings.enabled) return;
  await convertLinks(document);
  observeNewLinks();
}

async function getSettings() {
  const defaults = {
    apiBaseUrl: "http://localhost:8001",
    affiliateId: "",
    enabled: false,
    excludedDomains: [],
    excludedUrls: []
  };
  const stored = await chrome.storage.local.get(defaults);
  return { ...defaults, ...stored };
}

function isEligibleUrl(rawUrl, pageUrl, currentSettings) {
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
  if (currentSettings.excludedDomains.some((domain) =>
    target.hostname === domain || target.hostname.endsWith(`.${domain}`)
  )) return false;
  return !currentSettings.excludedUrls.some((url) => target.href === url);
}

async function convertLinks(root) {
  const links = [...root.querySelectorAll("a[href]")]
    .filter((link) => !processed.has(link))
    .slice(0, MAX_LINKS_PER_PAGE);
  for (const link of links) {
    processed.add(link);
    const targetUrl = new URL(link.href, window.location.href).href;
    if (!isEligibleUrl(targetUrl, window.location.href, settings)) continue;

    const result = await chrome.runtime.sendMessage({ type: "generate-deep-link", targetUrl });
    if (result?.ok && result.deeplinkUrl) {
      link.dataset.deerflowOriginalHref = link.href;
      link.href = result.deeplinkUrl;
      link.dataset.deerflowConverted = "true";
    }
  }
}

function observeNewLinks() {
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) void convertLinks(node);
      }
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
}
