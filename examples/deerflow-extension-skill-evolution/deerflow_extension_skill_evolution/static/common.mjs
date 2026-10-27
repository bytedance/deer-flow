export const zh = (context) => context.locale?.startsWith("zh");

// Status labels and structural expectations mirror the Python snapshot
// (status.py). Unknown or missing fields degrade to a placeholder instead of
// throwing: a newer backend must not brick an older page and vice versa.
export const PLACEHOLDER = "—";

export function node(tag, text = "", attrs = {}) {
  const element = document.createElement(tag);
  if (text !== "") element.textContent = text;
  Object.assign(element, attrs);
  return element;
}

export function label(context, value) {
  const t = (en, cn) => (zh(context) ? cn : en);
  if (value === true) return t("On", "已开启");
  if (value === false) return t("Off", "已关闭");
  if (value === "available") return t("Available", "可用");
  if (value === "unavailable") return t("Unavailable", "不可用");
  if (value === "granted") return t("Granted", "已授权");
  if (value === "not_granted") return t("Not granted", "未授权");
  if (value === "unreadable") return t("Unreadable", "无法读取");
  if (value === "lead") return t("Lead agent", "主 Agent");
  if (value === "lead_and_subagent") return t("Lead + subagents", "主 Agent 与子 Agent");
  return value == null ? PLACEHOLDER : String(value);
}

export function dot(tone) {
  return node("span", "", { className: `status-dot tone-${tone}` });
}

export function row(name, value, tone) {
  const item = node("div", "", { className: "status-row" });
  const key = node("span", name, { className: "status-key" });
  const body = node("span", "", { className: "status-value" });
  if (tone) body.append(dot(tone));
  body.append(node("span", value));
  item.append(key, body);
  if (tone) item.setAttribute("data-tone", tone);
  return item;
}

// Secondary deployment information folds away so the self-evolved skill list
// stays the primary content of the page.
export function fold(title, children) {
  const details = node("details", "", { className: "status-fold" });
  details.append(node("summary", title, { className: "status-fold-title" }));
  const list = node("div", "", { className: "status-list" });
  list.append(...children.filter(Boolean));
  details.append(list);
  return details;
}

export function text(context, en, cn) {
  return zh(context) ? cn : en;
}

