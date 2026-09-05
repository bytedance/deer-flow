import { getSettings } from "./shared.js";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "generate-deep-link") return undefined;

  generateDeepLink(message.targetUrl)
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
});

async function generateDeepLink(targetUrl) {
  const settings = await getSettings();
  if (!settings.enabled) throw new Error("擴充功能目前已停用");
  if (!settings.affiliateId.trim()) throw new Error("請先設定 aff_uniq_id");

  const baseUrl = settings.apiBaseUrl.replace(/\/+$/, "");
  const response = await fetch(`${baseUrl}/api/ad-links/deep-link`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_url: targetUrl,
      aff_uniq_id: settings.affiliateId.trim()
    })
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Gateway 回應 ${response.status}`);
  }
  if (!payload.deeplink_url) throw new Error("Gateway 沒有回傳導購連結");
  return { deeplinkUrl: payload.deeplink_url };
}
