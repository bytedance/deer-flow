import { getSettings } from "./shared.js";

const status = document.querySelector("#status");
const settings = await getSettings();
status.textContent = settings.enabled ? "已啟用：重新載入頁面後轉換連結" : "目前已停用";
document.querySelector("#options").addEventListener("click", () => chrome.runtime.openOptionsPage());
