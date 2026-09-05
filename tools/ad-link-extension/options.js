import { DEFAULT_SETTINGS, getSettings } from "./shared.js";

const ids = ["apiBaseUrl", "affiliateId", "enabled", "excludedDomains", "excludedUrls"];
const elements = Object.fromEntries(ids.map((id) => [id, document.querySelector(`#${id}`)]));
const settings = await getSettings();

elements.apiBaseUrl.value = settings.apiBaseUrl;
elements.affiliateId.value = settings.affiliateId;
elements.enabled.checked = settings.enabled;
elements.excludedDomains.value = settings.excludedDomains.join("\n");
elements.excludedUrls.value = settings.excludedUrls.join("\n");

elements.save.addEventListener("click", async () => {
  const apiBaseUrl = elements.apiBaseUrl.value.trim().replace(/\/+$/, "");
  if (!/^https?:\/\/[^/]+/.test(apiBaseUrl)) {
    elements.status.textContent = "Gateway URL 格式不正確";
    return;
  }
  await chrome.storage.local.set({
    ...DEFAULT_SETTINGS,
    apiBaseUrl,
    affiliateId: elements.affiliateId.value.trim(),
    enabled: elements.enabled.checked,
    excludedDomains: lines(elements.excludedDomains.value),
    excludedUrls: lines(elements.excludedUrls.value)
  });
  elements.status.textContent = "已儲存，請重新載入要轉換的網頁";
});

function lines(value) {
  return value.split(/\r?\n/).map((line) => line.trim().toLowerCase()).filter(Boolean);
}
