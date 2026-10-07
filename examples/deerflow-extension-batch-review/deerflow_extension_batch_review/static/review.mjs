// Native browser module: all report and excerpt text stays on textContent paths.
const SOURCE_ID = /^[a-f0-9]{32}-[1-9][0-9]{0,2}$/;

function node(tag, text, className = "") {
  const value = document.createElement(tag);
  if (text !== undefined) value.textContent = String(text);
  value.className = className;
  return value;
}

function button(text, action) {
  const value = node("button", text);
  value.type = "button";
  value.addEventListener("click", action);
  return value;
}

function sourceMap(evidence) {
  const sources = new Map();
  if (evidence?.version !== 1 || !Array.isArray(evidence.sources)) return sources;
  for (const source of evidence.sources.slice(0, 100)) {
    if (!SOURCE_ID.test(source?.id ?? "") || source.provider !== "ragflow" || typeof source.text !== "string" || sources.has(source.id)) continue;
    sources.set(source.id, source);
  }
  return sources;
}

// Literal report rendering preserves all text. Only native citation destinations
// gain actions; fenced/inline code remains literal and never creates a citation.
export function reportNodes(report, sources, showSource, unavailable) {
  const fragment = document.createDocumentFragment();
  // Process backtick runs once and precompute their next matching run. An
  // unclosed span stays literal; repeated unequal runs cannot trigger rescans.
  function appendText(text) {
    const tokens = [...text.matchAll(/(?<!\\)(`+)|(?<!!)\[([^\]\n]+)\]\(#knowledge-([a-f0-9]{32}-[1-9][0-9]{0,2})\)/g)];
    const nextRun = new Map();
    const closes = new Map();
    for (let i = tokens.length - 1; i >= 0; i--) {
      const run = tokens[i][1];
      if (!run) continue;
      if (nextRun.has(run.length)) closes.set(i, nextRun.get(run.length));
      nextRun.set(run.length, i);
    }
    let end = 0;
    for (let i = 0; i < tokens.length; i++) {
      const match = tokens[i];
      fragment.append(document.createTextNode(text.slice(end, match.index)));
      if (match[1]) {
        const closing = closes.get(i);
        if (closing !== undefined) {
          const close = tokens[closing];
          end = close.index + close[0].length;
          fragment.append(document.createTextNode(text.slice(match.index, end)));
          i = closing;
          continue;
        }
        fragment.append(document.createTextNode(match[0]));
      } else {
        const source = sources.get(match[3]);
        const citation = source ? button(match[2], () => showSource(source)) : node("span", match[2], "muted");
        citation.classList.add("citation");
        if (!source) citation.title = unavailable;
        fragment.append(citation);
      }
      end = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(text.slice(end)));
  }
  let pending = "";
  let fence = null;
  for (const line of report.match(/[^\n]*\n|[^\n]+$/g) ?? []) {
    const marker = /^ {0,3}(`{3,}|~{3,})([^\n]*)/.exec(line);
    if (fence || marker || /^(?: {4}|\t)/.test(line)) {
      if (pending) { appendText(pending); pending = ""; }
      fragment.append(document.createTextNode(line));
      if (fence) {
        if (marker && marker[1][0] === fence.kind && marker[1].length >= fence.length && marker[2].trim() === "") fence = null;
      } else if (marker) fence = { kind: marker[1][0], length: marker[1].length };
    } else pending += line;
  }
  if (pending) appendText(pending);
  return fragment;
}

export function mountReview(root, context) {
  const zh = context.locale.startsWith("zh");
  const text = (en, cn) => zh ? cn : en;
  let disposed = false;
  let thread = context.threadId ?? "";
  let batch = null;
  let selected = null;
  let rows = [];
  let moreItems = false;
  const tasks = new Map();
  const style = node("link");
  style.rel = "stylesheet";
  style.href = new URL("./style.css", import.meta.url).href;
  style.crossOrigin = "use-credentials";
  const introduction = node("p", text("Read saved reports and original captured evidence. Execution completion and acceptance are different. This page does not rerun work or contact a knowledge provider.", "查看保存的报告与原始检索证据。执行结束与验收通过分别展示。本页不会重新执行任务或访问知识提供方。"));
  const toolbar = node("form", undefined, "toolbar");
  const input = node("input");
  input.value = thread;
  input.maxLength = 128;
  input.required = true;
  input.setAttribute("aria-label", text("Conversation ID", "会话ID"));
  const load = node("button", text("Load reports", "加载报告"));
  load.type = "submit";
  toolbar.append(input, load);
  const layout = node("div", undefined, "layout");
  const sidebar = node("aside");
  const batches = node("div", undefined, "choices");
  batches.setAttribute("aria-label", text("Batches", "批任务"));
  const items = node("div", undefined, "choices");
  items.setAttribute("aria-label", text("Items", "任务项"));
  const detail = node("section");
  detail.setAttribute("aria-label", text("Saved result", "保存的结果"));
  detail.setAttribute("aria-live", "polite");
  sidebar.append(batches, items);
  layout.append(sidebar, detail);
  const dialog = node("dialog");
  root.replaceChildren(style, introduction, toolbar, layout, dialog);

  function stop(channel) {
    tasks.get(channel)?.abort();
    tasks.delete(channel);
  }

  function clearResult() {
    stop("result");
    selected = null;
    if (dialog.open) dialog.close();
    dialog.replaceChildren();
    detail.replaceChildren();
  }

  async function request(channel, action, payload, target, receive) {
    stop(channel);
    const controller = new AbortController();
    tasks.set(channel, controller);
    target.replaceChildren(node("p", text("Loading…", "加载中…"), "muted"));
    try {
      const value = await context.callBackend(action, payload, { signal: controller.signal });
      if (disposed || controller.signal.aborted || context.signal.aborted || tasks.get(channel) !== controller) return;
      target.replaceChildren();
      receive(value);
    } catch (error) {
      if (disposed || controller.signal.aborted || context.signal.aborted || tasks.get(channel) !== controller) return;
      const message = node("p", text("Unable to load saved results. Check access and storage, then retry.", "无法加载保存的结果，请检查访问权限和存储后重试。"), "error");
      message.setAttribute("role", "alert");
      target.replaceChildren(message, button(text("Retry read", "重新读取"), () => request(channel, action, payload, target, receive)));
    }
  }

  function showSource(source) {
    if (!selected) return;
    const heading = node("h2", source.document_name);
    heading.id = "batch-source-title";
    dialog.setAttribute("aria-labelledby", heading.id);
    const close = button(text("Close source", "关闭来源"), () => dialog.close());
    const metadata = node("p", `${source.dataset_name} · ${text("Pages", "页码")}: ${(source.pages ?? []).join(", ") || "—"}`);
    const excerpt = node("blockquote", source.text, "excerpt");
    dialog.replaceChildren(heading, metadata, node("p", text("Captured retrieved excerpt", "保存的检索原文"), "muted"), excerpt);
    if (source.truncated) dialog.append(node("p", text("The producer marked this excerpt as truncated.", "原始检索结果已标记为截断。"), "muted"));
    dialog.append(close);
    dialog.showModal();
    close.focus();
  }

  function showResult(value) {
    selected = value;
    const sources = sourceMap(value.evidence);
    detail.append(node("h2", value.item_key), node("p", `${text("Execution", "执行")}: ${value.status} · ${text("Attempt", "尝试")}: ${value.attempt}`));
    const criteria = Array.isArray(value.acceptance_criteria) ? value.acceptance_criteria : [];
    const verdict = value.acceptance_verdict;
    const acceptance = criteria.length === 0 ? text("Not requested", "未设置") : !verdict ? text("Unchecked", "未检查") : verdict.all_hold === true ? text("Verified", "已核验") : text("Not fully verified", "未全部核验");
    detail.append(node("p", `${text("Acceptance", "验收")}: ${acceptance}`));
    if (criteria.length > 0) {
      const list = node("ul");
      for (const criterion of criteria) list.append(node("li", criterion));
      detail.append(list);
    }
    if (verdict) detail.append(node("pre", JSON.stringify(verdict, null, 2), "report"));
    if (value.error) detail.append(node("p", value.error, "error"));
    if (value.stop_reason) detail.append(node("p", `${text("Stop reason", "停止原因")}: ${value.stop_reason}`));
    if (value.result !== null && typeof value.result === "string") {
      const report = node("div", undefined, "report");
      report.setAttribute("data-testid", "batch-saved-report");
      report.append(reportNodes(value.result, sources, showSource, text("Captured source unavailable", "保存的来源不可用")));
      detail.append(report);
    } else {
      detail.append(node("p", text("No saved report for this item yet.", "该任务项尚无保存的报告。"), "muted"));
    }
    if (value.result_truncated) detail.append(node("p", text("Stored report is truncated; this is not the complete original output.", "保存的报告已截断，并非原始完整输出。"), "muted"));
    if (!value.evidence) detail.append(node("p", text("No captured evidence snapshot. Legacy, pending and unsuccessful results may not have one.", "没有保存的证据快照；历史、未完成或未成功的结果可能没有证据。"), "muted"));
    else if (value.evidence.omitted_count > 0) detail.append(node("p", text(`${value.evidence.omitted_count} sources were omitted before storage.`, `存储前省略了${value.evidence.omitted_count}条来源。`), "muted"));
    if (sources.size > 0) {
      const list = node("div", undefined, "choices");
      list.setAttribute("aria-label", text("Captured sources", "保存的来源"));
      for (const source of sources.values()) list.append(button(source.document_name, () => showSource(source)));
      detail.append(list);
    }
    detail.append(button(text("Refresh selected result", "刷新所选结果"), () => selectItem(value)));
    if (context.openConversation) detail.append(button(text("Return to conversation and controls", "返回会话与任务控制"), () => {
      context.openConversation(thread).catch(() => {
        if (!disposed && !context.signal.aborted) detail.append(node("p", text("Conversation unavailable", "会话不可用"), "error"));
      });
    }));
  }

  function selectItem(item) {
    clearResult();
    request("result", "result", { thread_id: thread, batch_id: batch.id, position: item.position }, detail, showResult);
  }

  function renderItems() {
    items.replaceChildren();
    for (const item of rows) items.append(button(`${item.item_key} · ${item.status}`, () => selectItem(item)));
    if (rows.length === 0) items.append(node("p", text("No items", "没有任务项"), "muted"));
    if (moreItems) items.append(button(text("Load more items", "加载更多任务项"), () => loadItems(rows.length)));
  }

  function loadItems(offset) {
    clearResult();
    request("items", "items", { thread_id: thread, batch_id: batch.id, offset }, items, (page) => {
      if (!Array.isArray(page)) throw new Error("Invalid item page");
      rows = offset === 0 ? page : [...rows, ...page];
      moreItems = page.length === 50;
      renderItems();
    });
  }

  function selectBatch(value) {
    clearResult();
    batch = value;
    rows = [];
    loadItems(0);
  }

  function loadBatches() {
    for (const channel of [...tasks.keys()]) stop(channel);
    clearResult();
    batch = null;
    rows = [];
    items.replaceChildren();
    thread = input.value.trim();
    if (!thread || thread.length > 128) return;
    request("batches", "batches", { thread_id: thread }, batches, (values) => {
      if (!Array.isArray(values)) throw new Error("Invalid batch list");
      if (values.length === 0) batches.append(node("p", text("No visible saved batches for this conversation.", "该会话没有可见的保存批任务。"), "muted"));
      for (const value of values) batches.append(button(`${value.title} · ${value.status}`, () => selectBatch(value)));
      batches.append(node("p", text("Shows up to 20 recent batches. Use the native panel for controls and bulk export.", "显示最近最多20个批任务；控制与批量导出请使用原生面板。"), "muted"));
    });
  }

  toolbar.addEventListener("submit", (event) => { event.preventDefault(); loadBatches(); });
  function dispose() {
    if (disposed) return;
    disposed = true;
    for (const channel of [...tasks.keys()]) stop(channel);
    if (dialog.open) dialog.close();
    context.signal.removeEventListener("abort", dispose);
    root.replaceChildren();
  }
  context.signal.addEventListener("abort", dispose, { once: true });
  if (context.signal.aborted) dispose();
  else if (thread) loadBatches();
  return { dispose };
}
