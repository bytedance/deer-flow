const labels = {user: "用户", assistant: "助手", tool: "工具结果", compaction: "压缩", state_change: "状态变化", timing: "计时记录"};
const outcomes = {completed:"完成", failed:"失败", timeout:"超时", cancelled:"取消", interrupted:"中断"};
const thresholdStorageKey = "deerflow.trajectory.slowThresholdsMs";
const maxThresholdMs = 365 * 86400000;

function validThreshold(value) {
  return typeof value === "number" && value > 0 && value <= maxThresholdMs;
}

function loadThresholds() {
  try {
    const saved = JSON.parse(window.localStorage?.getItem(thresholdStorageKey) || "{}");
    return new Map(Object.entries(saved).filter(([key, value]) => ["model", "tool"].includes(key) && validThreshold(value)));
  } catch {
    return new Map();
  }
}

function applyThreshold(timing, overrides) {
  if (!timing) return timing;
  const specific = `${timing.operation}:${timing.name}`;
  const threshold = overrides.get(timing.operation);
  if (threshold === undefined || timing.slow_threshold_key === specific) return timing;
  return {...timing, slow_threshold_ms:threshold, is_slow:timing.duration_ms >= threshold};
}

export function measuredDuration(timing) {
  const value = timing?.duration_ms;
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}
export function durationLabel(timing) {
  const value = measuredDuration(timing);
  if (value === null) return "未记录";
  if (value < 1000) return `${value.toFixed(1)} ms`;
  if (value < 60000) return `${(value/1000).toFixed(2)} s`;
  return `${(value/60000).toFixed(2)} min`;
}

// Never sort snapshot timestamps into a claimed global execution order.
export function analyzeRows(rows, threadId) {
  const seen = new Set(), output = rows.filter(row => {
    if (row.row_id && seen.has(row.row_id)) return false;
    if (row.row_id) seen.add(row.row_id);
    return true;
  }).map(row => ({...row, tool_calls:(row.tool_calls || []).map(call => ({...call}))}));
  const turns = new Map(), orders = new Map(), pending = new Map(), invocations = new Map(), repeats = new Map(), results = new Map();
  for (const row of output) {
    const execution = row.subagent_source?.execution_id || null;
    const scope = JSON.stringify([row.checkpoint_ns || "", execution]);
    const independent=row.source === "runtime_timing";
    if (!independent) orders.set(scope, (orders.get(scope) || 0) + 1);
    if (row.kind === "user" && !row.updated) turns.set(scope, (turns.get(scope) || 0) + 1);
    const turn = turns.get(scope) || 0;
    row.analysis = {evidence:{thread_id:threadId || row.thread_id || null, checkpoint_ns:row.checkpoint_ns || "", execution_id:execution, checkpoint_id:row.checkpoint_id || null, message_id:row.id || null, tool_call_id:row.tool_call_id || null, row_id:row.row_id || null}, saved_order:independent ? null : orders.get(scope), order_basis:independent ? "operation_anchor" : "checkpoint_parent_chain", timestamp_basis:row.source === "runtime_timing" ? "operation_ended_at" : "checkpoint_saved_at", result_links:[]};
    for (const [callIndex,call] of row.tool_calls.entries()) {
      const key = JSON.stringify([scope, turn, row.id, call.id, callIndex]);
      const fact = {call_id:call.id, call_row_id:row.row_id, tool_name:call.name, issuing_message_id:row.id, call_index:callIndex, result_row_ids:[], association:"missing_result", repeat_index:null, repeat_count:null};
      call.analysis = fact;
      if (!call.id || !row.id || row.unidentified) {fact.association="missing_identity"; continue;}
      if (invocations.has(key)) {call.analysis=invocations.get(key); continue;}
      invocations.set(key, fact);
      const pendingKey=JSON.stringify([scope,turn,call.id]);
      if (!pending.has(pendingKey)) pending.set(pendingKey, []);
      pending.get(pendingKey).push(fact);
      if (call.args_fingerprint) {
        const repeatKey=JSON.stringify([scope,turn,call.name,call.args_fingerprint]);
        if (!repeats.has(repeatKey)) repeats.set(repeatKey, []);
        repeats.get(repeatKey).push(fact);
      }
    }
    if (row.kind === "tool") {
      const resultKey=JSON.stringify([scope,turn,row.id]);
      if (row.updated && row.id && results.has(resultKey)) {
        const original=results.get(resultKey);
        Object.assign(row.analysis,{association:original.association,result_links:original.result_links,tool_name:original.tool_name});
        continue;
      }
      const key=JSON.stringify([scope,turn,row.tool_call_id]), candidates=pending.get(key) || [];
      if (candidates.length === 1) {
        const call=candidates[0];
        call.result_row_ids.push(row.row_id); call.association="matched";
        Object.assign(row.analysis,{result_links:[call.call_row_id], association:"matched",tool_name:call.tool_name});
        row.analysis.evidence.issuing_message_id=call.issuing_message_id;
        pending.set(key, []);
      } else {
        row.analysis.association=candidates.length ? "ambiguous" : "missing_call";
        for (const call of candidates) call.association="ambiguous";
      }
      if (row.id) results.set(resultKey,row.analysis);
    }
  }
  for (const group of repeats.values()) group.forEach((fact,index) => Object.assign(fact,{repeat_index:index+1,repeat_count:group.length}));
  return annotateFindings(output);
}

export function toolFailure(row) {
  if (!["tool","timing"].includes(row.kind)) return null;
  const timing=row.timing || {}, meta=row.tool_meta || {};
  if (row.kind==="timing" && timing.operation!=="tool") return null;
  if (row.tool_status==="error" || meta.status==="error") return {confidence:"observed",basis:"tool_status",reason:"工具报告失败"};
  for (const process of row.process || []) {
    if (process.status==="timeout") return {confidence:"observed",basis:"process_status",reason:"进程超时"};
    if (Number.isInteger(process.exit_code) && process.exit_code!==0) return {confidence:"observed",basis:"process_exit_code",reason:`进程返回码 ${process.exit_code}`};
  }
  if (timing.operation==="tool" && ["failed","timeout"].includes(timing.outcome)) return {confidence:"observed",basis:"tool_timing",reason:timing.outcome==="timeout" ? "工具超时" : "工具执行失败"};
  if ((row.text || "").startsWith("Error:") && meta.status==="success" && meta.source!=="content_analysis") return {confidence:"inferred",basis:"status_text_conflict",reason:"工具标记成功，但输出以错误提示开头，需核对"};
  if ((row.text || "").startsWith("Error:")) return {confidence:"inferred",basis:"legacy_error_text",reason:"工具返回错误文本，旧记录状态待确认"};
  return null;
}

function annotateFindings(rows) {
  const turns=new Map(), failures=new Map(), targets=new Map(), callsByRow=new Map(), issued=new Set(), scopes=new Map();
  for (const row of rows) {
    const analysis=row.analysis, evidence=analysis.evidence;
    const execution=JSON.stringify([evidence.checkpoint_ns,evidence.execution_id]);
    if (row.kind==="user" && !row.updated) turns.set(execution,(turns.get(execution)||0)+1);
    const scope=JSON.stringify([execution,turns.get(execution)||0]);
    scopes.set(row.row_id,scope);
    const failure=toolFailure(row); analysis.tool_failure=failure;
    for (const call of row.tool_calls || []) {
      const fact=call.analysis;
      if (!("retry" in fact)) fact.retry=null;
      if (issued.has(fact) || ["ambiguous","missing_identity"].includes(fact.association)) continue;
      issued.add(fact);
      const signature=call.args_fingerprint ? JSON.stringify([call.name,call.args_fingerprint]) : null;
      const paths=call.operation_targets || [];
      let previous=signature ? failures.get(JSON.stringify([scope,signature])) : null;
      if (previous) fact.retry={kind:"same_call_after_failure",confidence:previous.failure.confidence,previous_call_row_id:previous.fact.call_row_id,previous_result_row_id:previous.row_id,reason:"失败后重复相同调用"};
      else {
        previous=paths.map(path=>targets.get(JSON.stringify([scope,path]))).find(Boolean);
        if (previous) fact.retry={kind:"same_target_after_failure",confidence:"inferred",previous_call_row_id:previous.fact.call_row_id,previous_result_row_id:previous.row_id,reason:"失败后再次访问同一路径，可能重试"};
      }
      if (!callsByRow.has(row.row_id)) callsByRow.set(row.row_id,[]);
      callsByRow.get(row.row_id).push({call,signature,paths,fact});
    }
    if (row.kind!=="tool" || analysis.association!=="matched") continue;
    for (const callRow of analysis.result_links) for (const {call,signature,paths,fact} of callsByRow.get(callRow) || []) {
      if (call.id!==row.tool_call_id || scopes.get(callRow)!==scope) continue;
      const record={fact,failure,row_id:row.row_id,signature};
      if (failure) {
        if (signature) failures.set(JSON.stringify([scope,signature]),record);
        for (const path of paths) targets.set(JSON.stringify([scope,path]),record);
      } else {
        if (signature) failures.delete(JSON.stringify([scope,signature]));
        for (const path of paths) {
          const key=JSON.stringify([scope,path]);
          if (signature && targets.get(key)?.signature===signature) targets.delete(key);
        }
      }
    }
  }
  return rows;
}

export function toolFindings(rows) {
  const findings=[], seenCalls=new Set(), seenResults=new Set();
  for (const row of rows) {
    const failure=row.analysis?.tool_failure;
    const resultKey=JSON.stringify([row.checkpoint_ns || "",row.subagent_source?.execution_id || null,row.id || row.row_id]);
    if (failure && !seenResults.has(resultKey)) {
      seenResults.add(resultKey);
      findings.push({kind:"failure",...failure,row_id:row.row_id,name:row.tool_name || row.analysis?.tool_name || row.timing?.name || "未知工具"});
    }
    for (const call of row.tool_calls || []) {
      const fact=call.analysis;
      if (!fact?.retry || seenCalls.has(fact)) continue;
      seenCalls.add(fact);
      const {kind:retryKind,...detail}=fact.retry;
      findings.push({kind:"retry",retry_kind:retryKind,...detail,row_id:row.row_id,name:call.name || "未知工具",repeat_index:fact.repeat_index});
    }
  }
  return findings;
}

// API pages are checkpoint batches; retain over-read rows for the next turn.
export class TurnBuffer {
  pending = [];
  seen = new Set();
  cursor = null;
  exhausted = false;
  get hasMore() { return !this.exhausted || this.pending.length > 0; }
  add(page) {
    const additions = page.rows.filter(row => {
      if (this.seen.has(row.row_id)) return false;
      this.seen.add(row.row_id);
      return true;
    });
    this.pending = [...additions, ...this.pending];
    this.cursor = page.next_cursor;
    this.exhausted = !this.cursor;
  }
  takeTurn() {
    for (let index = this.pending.length - 1; index >= 0; index--) {
      const row = this.pending[index];
      if (row.kind === "user" && !row.updated) return this.pending.splice(index);
    }
    // A missing historical boundary remains a partial segment, not an invented turn.
    if (this.exhausted && this.pending.length) return this.pending.splice(0);
    return null;
  }
}

function gatewayURL(path) {
  const moduleURL = new URL(import.meta.url);
  const at = moduleURL.pathname.indexOf("/api/plugins/");
  if (at < 0) throw new Error("无法确定 Gateway 地址");
  return new URL(`${moduleURL.pathname.slice(0, at)}${path}`, moduleURL.origin);
}
export function imageEndpoint(threadId, path) {
  if (!path.startsWith("/mnt/user-data/uploads/") || path.slice(1).split("/").some(part => !part || part === "." || part === "..") || /[\\\x00-\x1f]/.test(path) || !/\.(png|jpe?g|webp|gif)$/i.test(path)) throw new Error("无效的图片路径");
  return gatewayURL(`/api/threads/${encodeURIComponent(threadId)}/artifacts/${path.slice(1).split("/").map(encodeURIComponent).join("/")}`);
}
function endpoint(threadId, cursor) {
  const url = gatewayURL(`/api/ext-trajectory/threads/${encodeURIComponent(threadId)}/checkpoints`);
  if (cursor) url.searchParams.set("cursor", cursor);
  return url;
}
function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}

function createScrollableResults(list, label, visibleCount, signal) {
  const batchSize = 20;
  let rendered = 0;
  let appendNext = () => {};
  list.setAttribute("aria-label", label);

  function fitFirstRows() {
    const last = list.children[visibleCount - 1];
    if (last?.offsetHeight) {
      list.style.maxHeight = `${last.offsetTop + last.offsetHeight}px`;
    }
  }
  const resize = globalThis.ResizeObserver ? new ResizeObserver(fitFirstRows) : null;
  signal.addEventListener("abort", () => resize?.disconnect(), {once:true});
  list.addEventListener("scroll", () => {
    if (list.scrollHeight - list.scrollTop <= list.clientHeight * 2) appendNext();
  }, {signal, passive:true});
  list.addEventListener("focusin", event => {
    if (event.target.closest("li") === list.lastElementChild) appendNext();
  }, {signal});

  return (results, renderResult, emptyMessage) => {
    const scrollTop = list.scrollTop || 0;
    const initialCount = scrollTop > 0 ? Math.max(rendered, batchSize) : batchSize;
    resize?.disconnect();
    list.replaceChildren();
    list.tabIndex = results.length > visibleCount ? 0 : -1;
    rendered = 0;
    appendNext = (count = batchSize) => {
      const end = Math.min(rendered + count, results.length);
      for (; rendered < end; rendered++) renderResult(results[rendered]);
    };
    appendNext(initialCount);
    if (!results.length) element("li", emptyMessage, list);
    if (resize) {
      if (results.length > visibleCount) {
        for (const item of Array.from(list.children).slice(0, visibleCount)) resize.observe(item);
        fitFirstRows();
      } else {
        list.style.removeProperty("max-height");
      }
    }
    list.scrollTop = scrollTop;
  };
}

const iconShapes = {
  user:'<circle cx="12" cy="8" r="4"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',
  bot:'<path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2m16 0h2M9 13v2m6-2v2"/>',
  wrench:'<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z"/>',
  history:'<path d="M3 11a9 9 0 1 1 2.4 7.1M3 4v7h7m2-4v5l3 2"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  timer:'<circle cx="12" cy="14" r="8"/><path d="M9 2h6m-3 12 3-3m3-6 2 2"/>',
  scan:'<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m8 0h3a2 2 0 0 0 2-2v-3M8 12h8"/>',
  archive:'<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v12h14V8m-10 4h6"/>',
};
function icon(name, parent) {
  const node = element("span", undefined, parent);
  node.className = "trajectory-icon";
  node.setAttribute("aria-hidden", "true");
  node.setAttribute("data-icon", name);
  // Only these package-owned shapes enter markup; message content uses textContent.
  node.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${iconShapes[name] || iconShapes.archive}</svg>`;
  return node;
}
function panelSummary(summary, title, name) {
  icon(name, summary);
  const content = element("span", undefined, summary);
  content.className = "trajectory-panel-label";
  element("span", title, content).className = "trajectory-panel-title";
  const stats = element("span", "", content);
  stats.className = "trajectory-panel-stats";
  return stats;
}
function comparisonMessages(parent, messages) {
  for (const message of messages) {
    const item = element("div", undefined, parent);
    item.className = "trajectory-comparison-message";
    element("strong", `${labels[message.kind] || message.kind}${message.tool_name ? ` · ${message.tool_name}` : ""}`, item);
    const content = message.content;
    const text = typeof content === "string" ? content : (Array.isArray(content) ? JSON.stringify(content, null, 2) : (message.text ?? ""));
    if (text) element("pre", text, item);
    for (const call of message.tool_calls || []) {
      element("strong", `调用工具 · ${call.name || "未知工具"}`, item);
      element("pre", call.args || "（无参数）", item);
    }
    if (message.tool_status) element("small", `工具状态：${message.tool_status}`, item);
  }
}
function renderComparison(container, data) {
  container.replaceChildren();
  element("p", "根据相邻保存快照对比：左侧为移除的消息及此前摘要，右侧为新摘要。移除不等于信息丢失；此处不是完整模型请求或精确压缩输入映射。", container).className = "trajectory-comparison-note";
  if (data.omitted_before_count || data.omitted_after_count) {
    element("p", `沿用轨迹可见性规则，系统或隐藏消息未展示（压缩前 ${data.omitted_before_count} 条，压缩后 ${data.omitted_after_count} 条）。`, container);
  }
  const columns = element("div", undefined, container);
  columns.className = "trajectory-comparison-columns";
  const before = element("section", undefined, columns);
  before.className = "trajectory-comparison-pane trajectory-comparison-before";
  before.setAttribute("aria-label", "压缩前");
  element("h3", "压缩前", before);
  const beforeBody = element("div", undefined, before);
  beforeBody.className = "trajectory-comparison-content";
  element("h4", "此前摘要", beforeBody);
  element("pre", data.before_summary || "（此前没有摘要）", beforeBody);
  element("h4", `本次移除的消息（${data.removed_messages.length} 条）`, beforeBody);
  comparisonMessages(beforeBody, data.removed_messages);
  if (!data.removed_messages.length) element("p", "本次快照差异中没有可展示的移除消息。", beforeBody);
  const after = element("section", undefined, columns);
  after.className = "trajectory-comparison-pane trajectory-comparison-after";
  after.setAttribute("aria-label", "压缩后");
  element("h3", "压缩后", after);
  const afterBody = element("div", undefined, after);
  afterBody.className = "trajectory-comparison-content";
  element("h4", "新摘要", afterBody);
  element("pre", data.after_summary || "（摘要为空）", afterBody);
  const kept = element("details", undefined, afterBody);
  element("summary", `查看压缩后保留的消息（${data.retained_messages.length} 条）`, kept);
  comparisonMessages(kept, data.retained_messages);
}
function rowView(row, locale, toolNames, expandedRows, addImages, addComparison) {
  const item = element("li");
  item.className = `trajectory-row trajectory-${row.kind}${row.subagent_source ? " trajectory-subagent-row" : ""}`;
  item.setAttribute("data-row-id", row.row_id);
  if (row.subagent_source) {
    item.setAttribute("data-execution-id", row.subagent_source.execution_id);
    item.setAttribute("data-parent-row-id", row.subagent_source.parent_row_id);
  }
  const box = element("details", undefined, item);
  box.open = expandedRows.has(row.row_id);
  const summary = element("summary", undefined, box);
  summary.className = "trajectory-line";
  const roleIcon = icon(row.kind === "assistant" ? "bot" : row.kind === "tool" ? "wrench" : row.kind === "user" ? "user" : row.kind === "timing" ? "timer" : "archive", summary);
  roleIcon.className += ` trajectory-role-icon${row.kind === "assistant" ? " trajectory-assistant-icon" : ""}`;
  element("strong", `${row.subagent_source ? `子 agent · ${row.subagent_source.name} · ` : ""}${labels[row.kind] || row.kind}`, summary).className = "trajectory-kind";
  const toolName = row.tool_name || row.analysis?.tool_name || (row.analysis ? null : toolNames.get(row.tool_call_id)) || "未知工具";
  const text = row.display_text ?? row.text;
  let preview = text || "";
  if (row.images?.length) preview = [`图片 ×${row.images.length}`, preview].filter(Boolean).join(" · ");
  if (row.kind === "tool") preview = `${toolName}${row.tool_status === "error" ? " · 返回错误" : ""} · ${preview}`;
  else if (row.kind === "compaction" || row.kind === "state_change") preview = `可见消息 ${row.before_count} → ${row.after_count} · ${preview}`;
  else if (row.tool_calls?.length) preview = [preview, ...row.tool_calls.map(call => `调用 ${call.name || "未知工具"} ${call.args || ""}`)].filter(Boolean).join(" · ");
  element("span", preview.replace(/\s+/g, " ").trim() || "（无文本内容）", summary).className = "trajectory-preview";
  const failure=row.analysis?.tool_failure;
  if (failure) element("span",failure.confidence==="observed" ? "失败" : "待核对",summary).className=failure.confidence==="observed" ? "trajectory-anomaly" : "trajectory-status";
  const hasTimingLine = ["assistant","tool","timing"].includes(row.kind);
  const timestamp = new Date(row.created_at).toLocaleString(locale);
  if (hasTimingLine) {
    if (row.timing?.is_slow) element("span", "慢", summary).className = "trajectory-slow";
    const outcome = row.timing?.outcome ?? (row.model_error_fallback ? "failed" : null);
    if (outcome && outcome !== "completed" && !failure) element("span", outcomes[outcome] || outcome, summary).className = ["failed","timeout"].includes(outcome) ? "trajectory-anomaly" : "trajectory-status";
    const duration = element("small", durationLabel(row.timing), summary);
    duration.className = "trajectory-duration";
    duration.title = row.timing?.operation === "model" ? "模型完整响应耗时（包含宿主重试及流式输出完成）" : "工具调用耗时";
  }
  const body = element("div", undefined, box);
  body.className = "trajectory-body";
  if (hasTimingLine) {
    const timing = row.timing;
    const label = timing?.operation === "model" ? "模型完整响应耗时" : "工具调用耗时";
    element("p", `${timestamp} · ${timing ? `${label}：${durationLabel(timing)} · 状态：${outcomes[timing.outcome] || timing.outcome} · 慢阈值：${timing.slow_threshold_ms == null ? "未配置" : durationLabel({duration_ms:timing.slow_threshold_ms})}` : `耗时：未记录${row.model_error_fallback ? " · 状态：失败" : ""}`}`, body).className = "trajectory-timing-note";
  }
  else element("p", timestamp, body).className = "trajectory-timing-note";
  if (row.kind === "tool" && (toolName === "bash" || row.process?.length)) {
    element("p", `进程返回码：${row.process?.length ? row.process.map(item=>`${item.exit_code ?? "未记录"}（${item.source} · ${outcomes[item.status] || item.status}）`).join("；") : "未记录"}`,body);
  }
  if (row.timing?.error_type) element("p", `异常类型：${row.timing.error_type}`, body);
  if (row.kind === "tool") element("strong", `${toolName}${row.tool_status === "error" ? " · 返回错误" : ""}`, body);
  if (row.kind === "compaction" || row.kind === "state_change") element("strong", `可见消息 ${row.before_count} → ${row.after_count}`, body);
  if (row.kind === "compaction") addComparison(body, box, row);
  else if (text) element("pre", text, body);
  if (row.images?.length) {
    addImages(body, box, row.images);
    const raw = element("details", undefined, body);
    element("summary", "上传文件说明", raw);
    element("pre", row.text, raw);
  }
  for (const call of row.tool_calls || []) {
    element("strong", `调用工具 · ${call.name || "未知工具"}`, body);
    element("pre", call.args || "（无参数）", body);
  }
  if (!text && !row.tool_calls?.length && !row.images?.length) element("p", "（无文本内容）", body);
  if (row.truncated && row.kind !== "compaction") element("small", "内容过长，单项仅展示前 4000 个字符。", body);
  box.addEventListener("toggle", () => {
    if (!box.isConnected) return;
    if (box.open) expandedRows.add(row.row_id);
    else expandedRows.delete(row.row_id);
  });
  return item;
}

export default {
  apiVersion: 1,
  module: "trajectory.v1",
  surfaces: [{
    id: "viewer", slot: "page", title: "运行轨迹",
    mount(root, context) {
      const threadId = new URLSearchParams(window.location.search).get("thread_id");
      // Keep the heading and export action together inside this surface. Restore
      // the host wrapper when navigation disposes the plugin.
      const host = root.getRootNode?.().host;
      const page = host?.parentElement?.parentElement;
      if (page?.parentElement?.tagName === "MAIN" && page.querySelector(":scope > h1")) {
        const prior = page.style.getPropertyValue("padding-top");
        const priority = page.style.getPropertyPriority("padding-top");
        const heading = page.querySelector(":scope > h1");
        const headingDisplay = heading.style.getPropertyValue("display");
        const headingPriority = heading.style.getPropertyPriority("display");
        page.style.setProperty("padding-top", "16px");
        heading.style.setProperty("display", "none");
        context.signal.addEventListener("abort", () => {
          if (page.style.getPropertyValue("padding-top") === "16px") {
            if (prior) page.style.setProperty("padding-top", prior, priority);
            else page.style.removeProperty("padding-top");
          }
          if (heading.style.getPropertyValue("display") === "none") {
            if (headingDisplay) heading.style.setProperty("display", headingDisplay, headingPriority);
            else heading.style.removeProperty("display");
          }
        }, {once:true});
      }
      const shell = element("section", undefined, root);
      shell.className = "trajectory";
      element("style", `
.trajectory{--tr-surface:var(--card,Canvas);--tr-text:var(--foreground,CanvasText);--tr-muted:var(--muted-foreground,GrayText);--tr-line:var(--border,color-mix(in srgb,CanvasText 12%,Canvas));--tr-soft:var(--secondary,color-mix(in srgb,CanvasText 5%,Canvas));--tr-accent:light-dark(#47664d,#a9c9ae);--tr-warning:light-dark(#94651c,#ebbd70);--tr-warning-bg:light-dark(#faf1df,#3a3020);width:100%;margin:0;padding:0;color:var(--tr-text);font:400 14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.trajectory *{box-sizing:border-box}
.trajectory [hidden]{display:none!important}
.trajectory .trajectory-header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}
.trajectory .trajectory-heading{margin:0;font-family:inherit;font-size:24px;font-weight:600;line-height:1.35;letter-spacing:-.6px}
.trajectory .trajectory-icon{display:inline-flex;align-items:center;justify-content:center;flex:none;color:var(--tr-muted);width:16px;height:16px}
.trajectory .trajectory-icon svg{width:100%;height:100%}
.trajectory .trajectory-controls{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
.trajectory button,.trajectory .trajectory-export>summary{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:7px 12px;margin:0;min-height:34px;border:1px solid var(--tr-line);border-radius:8px;background:var(--tr-surface);color:var(--tr-text);font-family:inherit;font-weight:400;font-size:12px;line-height:1.5;cursor:pointer}
.trajectory button:hover:not(:disabled),.trajectory .trajectory-export>summary:hover{background:var(--tr-soft)}
.trajectory button:disabled{opacity:.45;cursor:default}
.trajectory .trajectory-refresh{background:var(--primary,CanvasText);border-color:var(--primary,CanvasText);color:var(--primary-foreground,Canvas)}
.trajectory .trajectory-refresh:hover:not(:disabled){background:color-mix(in srgb,var(--primary,CanvasText) 88%,var(--tr-surface))}
.trajectory .trajectory-export{position:relative;flex:none}
.trajectory .trajectory-export>summary{list-style:none}
.trajectory .trajectory-export>summary::after{content:"⌄";margin-left:2px;color:var(--tr-muted)}
.trajectory .trajectory-export-menu{position:absolute;right:0;top:calc(100% + 7px);z-index:2;display:flex;flex-direction:column;gap:6px;min-width:210px;max-width:calc(100vw - 40px);padding:8px;background:var(--tr-surface);border:1px solid var(--tr-line);border-radius:10px;box-shadow:0 8px 24px color-mix(in srgb,var(--tr-text) 10%,transparent)}
.trajectory .trajectory-export-menu button{justify-content:flex-start;border-color:transparent}
.trajectory ol{list-style:none;padding:0;margin:0}
.trajectory .trajectory-diagnostics{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;align-items:start;margin-bottom:22px}
@media(min-width:641px){.trajectory .trajectory-diagnostics:has(>.trajectory-timing-panel[open]):has(>.trajectory-tools-panel[open]){align-items:stretch}}
.trajectory .trajectory-timing-panel,.trajectory .trajectory-tools-panel{min-width:0;border:1px solid var(--tr-line);border-radius:12px;background:var(--tr-surface);padding:0 14px 12px}
.trajectory .trajectory-timing-panel:not([open]),.trajectory .trajectory-tools-panel:not([open]){padding-bottom:0}
.trajectory .trajectory-timing-panel>summary,.trajectory .trajectory-tools-panel>summary{display:flex;align-items:center;gap:11px;padding:12px 0;list-style:none;cursor:pointer}
.trajectory .trajectory-timing-panel>summary::after,.trajectory .trajectory-tools-panel>summary::after{content:"›";margin-left:auto;color:var(--tr-muted);font-size:18px}
.trajectory .trajectory-diagnostics details[open]>summary::after{transform:rotate(90deg)}
.trajectory .trajectory-panel-label{display:flex;flex-direction:column;min-width:0}
.trajectory .trajectory-panel-title{font-size:12px;color:var(--tr-muted)}
.trajectory .trajectory-panel-stats{font-size:13px;font-weight:500;overflow-wrap:anywhere}
.trajectory .trajectory-timing-panel p,.trajectory .trajectory-tools-panel p{font-size:12px;color:var(--tr-muted);margin:0 0 12px;overflow-wrap:anywhere}
.trajectory .trajectory-timing-filter,.trajectory .trajectory-tools-filter{max-width:100%;padding:6px 9px;border:1px solid var(--tr-line);border-radius:7px;background:var(--tr-surface);color:var(--tr-text);font:inherit;font-size:12px;margin-bottom:8px}
.trajectory .trajectory-threshold-settings{margin-bottom:8px;font-size:12px}
.trajectory .trajectory-threshold-settings>summary{width:fit-content;cursor:pointer;color:var(--tr-text)}
.trajectory .trajectory-threshold-settings form{margin-top:8px;padding:10px;border:1px solid var(--tr-line);border-radius:8px;background:var(--tr-soft)}
.trajectory .trajectory-threshold-fields{display:grid;gap:6px;margin:8px 0;max-height:240px;overflow:auto}
.trajectory .trajectory-threshold-fields label{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,100px);align-items:center;gap:8px;overflow-wrap:anywhere}
.trajectory .trajectory-threshold-fields input{box-sizing:border-box;width:100%;padding:6px;border:1px solid var(--tr-line);border-radius:6px;background:var(--tr-surface);color:var(--tr-text);font:inherit}
.trajectory .trajectory-threshold-status{min-height:1em}
.trajectory .trajectory-timing-list,.trajectory .trajectory-tools-list{position:relative;display:flex;flex-direction:column;gap:5px;overflow-y:auto;scrollbar-width:thin}
.trajectory .trajectory-timing-list li,.trajectory .trajectory-tools-list li{flex:none;min-width:0}
.trajectory .trajectory-timing-list button,.trajectory .trajectory-tools-list button{text-align:left;justify-content:flex-start;max-width:100%;overflow-wrap:anywhere}
.trajectory .trajectory-turn{margin:0 0 22px;min-width:0}
.trajectory .trajectory-turn-title{display:flex;align-items:center;gap:10px;position:relative;font-size:13px;font-weight:600;padding:0 0 11px;cursor:pointer;list-style:none}
.trajectory .trajectory-turn-title::after{content:"";height:1px;flex:1;background:var(--tr-line)}
.trajectory .trajectory-turn-title::before{content:"▸";font-size:11px;font-weight:400;color:var(--tr-muted)}
.trajectory details[open]>.trajectory-turn-title::before{content:"▾"}
.trajectory .trajectory-turn-count{order:1;font-size:11px;font-weight:400;color:var(--tr-muted);font-variant-numeric:tabular-nums}
.trajectory .trajectory-turn-rows{border:1px solid var(--tr-line);border-radius:12px;overflow:hidden;background:var(--tr-surface)}
.trajectory .trajectory-row{margin:0;min-width:0;background:var(--tr-surface)}
.trajectory .trajectory-row+.trajectory-row{border-top:1px solid var(--tr-line)}
.trajectory .trajectory-line{display:flex;align-items:center;gap:10px;padding:12px 14px;min-width:0;min-height:48px;cursor:pointer;list-style:none}
.trajectory .trajectory-line::before{content:"›";font-size:17px;line-height:1;flex:none;color:var(--tr-muted)}
.trajectory details[open]>.trajectory-line::before{transform:rotate(90deg)}
.trajectory .trajectory-line:hover,.trajectory details[open]>.trajectory-line{background:color-mix(in srgb,var(--tr-soft) 55%,var(--tr-surface))}
.trajectory .trajectory-user{--tr-role:light-dark(#335f99,#98b9ed)}
.trajectory .trajectory-assistant{--tr-role:var(--tr-accent)}
.trajectory .trajectory-tool{--tr-role:light-dark(#8d601c,#e5bc7a)}
.trajectory .trajectory-role-icon{width:24px;height:24px;padding:4px;border-radius:7px;background:color-mix(in srgb,var(--tr-role,var(--tr-muted)) 10%,var(--tr-surface));color:var(--tr-role,var(--tr-muted))}
.trajectory .trajectory-kind{flex:0 0 48px;color:var(--tr-role,var(--tr-muted));font-size:12px;font-weight:500}
.trajectory .trajectory-preview{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}
.trajectory .trajectory-body{padding:10px 20px 20px 112px}
.trajectory .trajectory-body>strong{display:block;font-size:13px;font-weight:500;margin:10px 0 7px}
.trajectory pre{white-space:pre-wrap;overflow-wrap:anywhere;font:400 13px/1.75 "SFMono-Regular",Consolas,"Liberation Mono",monospace;max-height:420px;overflow:auto;margin:7px 0 12px;padding:12px 14px;border-radius:7px;background:var(--tr-soft);color:var(--tr-text)}
.trajectory .trajectory-body p{margin:4px 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}
.trajectory .trajectory-timing-note{font-size:12px;color:var(--tr-muted);font-variant-numeric:tabular-nums}
.trajectory .trajectory-duration{flex:0 0 auto;min-width:62px;text-align:right;white-space:nowrap;font-size:12px;color:var(--tr-muted);font-variant-numeric:tabular-nums}
.trajectory .trajectory-slow,.trajectory .trajectory-anomaly,.trajectory .trajectory-status{flex:none;border-radius:5px;padding:2px 7px;font-size:11px;font-weight:400;line-height:1.6}
.trajectory .trajectory-status,.trajectory .trajectory-slow{background:var(--tr-warning-bg);color:var(--tr-warning)}
.trajectory .trajectory-anomaly{color:var(--destructive,CanvasText);background:color-mix(in srgb,var(--destructive,CanvasText) 10%,var(--tr-surface))}
.trajectory .trajectory-child-heading{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;padding:14px 16px 10px;overflow-wrap:anywhere;background:var(--tr-soft);border-top:1px solid var(--tr-line);border-bottom:1px solid var(--tr-line);font-size:12px}
.trajectory .trajectory-child-heading strong{font-weight:500}
.trajectory .trajectory-child-status{padding:10px 16px;font-size:12px;color:var(--tr-muted);overflow-wrap:anywhere}
.trajectory .trajectory-child-status button{margin:4px 0}
.trajectory .trajectory-subagent-row .trajectory-kind{flex:0 1 auto;max-width:35%;white-space:normal;overflow-wrap:anywhere}
.trajectory .trajectory-comparison{margin-top:8px}
.trajectory .trajectory-comparison-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;margin-top:10px}
.trajectory .trajectory-comparison-pane{min-width:0;border:1px solid var(--tr-line);border-radius:8px;overflow:hidden}
.trajectory .trajectory-comparison-pane h3{margin:0;padding:10px 12px;font-size:14px;font-weight:500;background:var(--tr-soft);border-bottom:1px solid var(--tr-line)}
.trajectory .trajectory-comparison-content{max-height:560px;overflow:auto;padding:0 12px 12px}
.trajectory .trajectory-comparison-content h4{margin:12px 0 6px;font-size:13px;font-weight:500}
.trajectory .trajectory-comparison-content pre{max-height:none;margin:6px 0;overflow:visible}
.trajectory .trajectory-comparison-message{padding:10px 0;border-bottom:1px solid var(--tr-line)}
.trajectory .trajectory-comparison-note{font-size:12px;color:var(--tr-muted)}
.trajectory .trajectory-comparison-content>details{margin-top:16px}
.trajectory .trajectory-located{outline:2px solid var(--ring,CanvasText);outline-offset:-2px}
.trajectory small{font-size:12px;color:var(--tr-muted)}
.trajectory [role="status"]:empty,.trajectory .trajectory-warnings:empty{display:none}
.trajectory [role="status"],.trajectory .trajectory-warnings{font-size:12px;overflow-wrap:anywhere;margin:0 0 12px}
.trajectory .trajectory-warnings{color:var(--tr-warning)}
.trajectory .trajectory-pagination{display:flex;align-items:center;gap:10px;margin-bottom:14px;font-size:12px;color:var(--tr-muted)}
.trajectory button:focus-visible,.trajectory summary:focus-visible,.trajectory select:focus-visible{outline:2px solid var(--ring,CanvasText);outline-offset:3px}
.trajectory .trajectory-timing-list:focus-visible,.trajectory .trajectory-tools-list:focus-visible,.trajectory .trajectory-timing-list button:focus-visible,.trajectory .trajectory-tools-list button:focus-visible{outline:2px solid var(--ring,CanvasText);outline-offset:-2px}
.trajectory summary::-webkit-details-marker{display:none}
.trajectory .trajectory-images{display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 12px}
.trajectory .trajectory-image-card{display:flex;align-items:center;gap:12px;text-align:left;max-width:100%;background:var(--tr-soft)}
.trajectory .trajectory-image-card img{width:100px;height:76px;object-fit:contain;border-radius:5px}
.trajectory .trajectory-image-card span{overflow-wrap:anywhere}
.trajectory dialog{max-width:92vw;max-height:92vh;border:1px solid var(--tr-line);border-radius:12px;padding:16px;background:var(--tr-surface);color:var(--tr-text)}
.trajectory dialog::backdrop{background:color-mix(in srgb,CanvasText 55%,transparent)}
.trajectory dialog img{display:block;max-width:85vw;max-height:75vh;object-fit:contain;margin-top:12px}
@media(max-width:640px){.trajectory .trajectory-heading{font-size:22px}.trajectory .trajectory-header{gap:10px;margin-bottom:18px}.trajectory .trajectory-diagnostics{grid-template-columns:minmax(0,1fr);gap:8px}.trajectory .trajectory-line{gap:6px;padding:12px 10px;flex-wrap:wrap}.trajectory .trajectory-kind{flex-basis:40px;font-size:11px}.trajectory .trajectory-preview{min-width:60px;font-size:13px}.trajectory .trajectory-subagent-row .trajectory-kind{max-width:43%;font-size:11px}.trajectory .trajectory-role-icon{width:22px;height:22px}.trajectory .trajectory-duration{min-width:52px;font-size:11px}.trajectory .trajectory-body{padding:10px 14px 18px}.trajectory .trajectory-comparison-columns{grid-template-columns:minmax(0,1fr)}.trajectory button,.trajectory .trajectory-export>summary,.trajectory select{min-height:44px}}
`, shell);
      const header = element("div", undefined, shell);
      header.className = "trajectory-header";
      element("h1", "运行轨迹", header).className = "trajectory-heading";
      const status = element("p", "", shell);
      status.setAttribute("role", "status");
      const controls = element("div", undefined, shell);
      controls.className = "trajectory-controls";
      const refresh = element("button", "最新一轮", controls);
      refresh.className = "trajectory-refresh";
      const older = element("button", "加载更早记录", controls);
      const historyIcon = icon("history", older);
      older.prepend?.(historyIcon);
      const all = element("button", "读取整个对话", controls);
      const exportMenu = element("details", undefined, header);
      exportMenu.className = "trajectory-export";
      const exportSummary = element("summary", "导出轨迹", exportMenu);
      const downloadIcon = icon("download", exportSummary);
      exportSummary.prepend?.(downloadIcon);
      const exportChoices = element("div", undefined, exportMenu);
      exportChoices.className = "trajectory-export-menu";
      const exportMarkdown = element("button", "Markdown＋图片 ZIP", exportChoices);
      const exportJSON = element("button", "JSON", exportChoices);
      const exportStatus = element("p", "", shell);
      exportStatus.setAttribute("role", "status");
      const warnings = element("p", "", shell);
      warnings.className = "trajectory-warnings";
      const diagnostics = element("div", undefined, shell);
      diagnostics.className = "trajectory-diagnostics";
      const timingPanel = element("details", undefined, diagnostics);
      timingPanel.className = "trajectory-timing-panel";
      const timingSummary = element("summary", undefined, timingPanel);
      const timingStats = panelSummary(timingSummary, "耗时定位", "timer");
      element("p", "仅比较当前已加载步骤；模型耗时覆盖完整响应，工具分别计时。并行耗时不相加为整轮耗时。慢阈值按操作类型配置，与异常状态分别判断。", timingPanel);
      const timingFilter = element("select", undefined, timingPanel);
      timingFilter.className = "trajectory-timing-filter";
      timingFilter.setAttribute("aria-label", "耗时定位范围");
      for (const [value, text] of [["all","全部已记录步骤"],["slow","超过慢阈值"],["failed","异常步骤"]]) element("option", text, timingFilter).value = value;
      timingFilter.value = "all";
      let thresholdOverrides = loadThresholds();
      const thresholdSettings = element("details", undefined, timingPanel);
      thresholdSettings.className = "trajectory-threshold-settings";
      element("summary", "设置慢阈值", thresholdSettings);
      const thresholdForm = element("form", undefined, thresholdSettings);
      element("p", "留空沿用宿主配置。", thresholdForm);
      const thresholdFields = element("div", undefined, thresholdForm);
      thresholdFields.className = "trajectory-threshold-fields";
      element("button", "保存慢阈值", thresholdForm).type = "submit";
      const thresholdStatus = element("p", "", thresholdForm);
      thresholdStatus.className = "trajectory-threshold-status";
      thresholdStatus.setAttribute("role", "status");
      const thresholdInputs = new Map();
      for (const [operation, title] of [["model", "模型（s）"], ["tool", "工具（s）"]]) {
        const label = element("label", undefined, thresholdFields);
        element("span", title, label);
        const input = element("input", undefined, label);
        input.type = "number";
        input.step = "any";
        input.max = String(maxThresholdMs / 1000);
        input.placeholder = "默认无限制";
        input.value = thresholdOverrides.has(operation) ? String(thresholdOverrides.get(operation) / 1000) : "";
        thresholdInputs.set(operation, input);
      }
      thresholdForm.addEventListener("submit", event => {
        event.preventDefault();
        const next = new Map();
        for (const [key, input] of thresholdInputs) {
          if (input.value === "") continue;
          const ms = Number(input.value) * 1000;
          if (!validThreshold(ms)) {
            thresholdStatus.textContent = "请输入大于 0 秒的有效阈值。";
            input.focus();
            return;
          }
          next.set(key, ms);
        }
        const data = JSON.stringify(Object.fromEntries(next));
        thresholdOverrides = next;
        try {
          window.localStorage.setItem(thresholdStorageKey, data);
          thresholdStatus.textContent = "已保存，当前浏览器使用此设置。";
        } catch {
          thresholdStatus.textContent = "已在本页应用。浏览器未能保存设置。";
        }
        render();
      });
      const timingList = element("ol", undefined, timingPanel);
      timingList.className = "trajectory-timing-list";
      timingFilter.addEventListener("change", () => {timingList.scrollTop = 0; render();});
      const toolsPanel=element("details",undefined,diagnostics);
      toolsPanel.className="trajectory-tools-panel";
      const toolsSummary=element("summary",undefined,toolsPanel);
      const toolsStats=panelSummary(toolsSummary,"工具失败与重试","scan");
      element("p","仅分析已加载步骤。失败依据工具状态和执行记录；错误文本与成功状态冲突时单列为待核对。失败后重复相同调用可直接核对；换工具访问同一路径仅提示可能重试。未记录的工具内部重试不计入。",toolsPanel);
      const toolsFilter=element("select",undefined,toolsPanel);
      toolsFilter.className="trajectory-tools-filter";
      toolsFilter.setAttribute("aria-label","工具失败与重试范围");
      for (const [value,text] of [["all","全部"],["failure","失败与待核对"],["repeat","失败后相同调用"],["possible","可能重试"]]) element("option",text,toolsFilter).value=value;
      toolsFilter.value="all";
      const toolsList=element("ol",undefined,toolsPanel); toolsList.className="trajectory-tools-list";
      toolsFilter.addEventListener("change",()=>{toolsList.scrollTop = 0; render();});
      const list = element("ol", undefined, shell);
      const pagination = element("nav", undefined, shell);
      pagination.className = "trajectory-pagination";
      pagination.setAttribute("aria-label", "轨迹分页");
      pagination.hidden = true;
      const previous = element("button", "上一页", pagination);
      const pageLabel = element("span", "", pagination);
      const next = element("button", "下一页", pagination);
      let rows = [], buffer = new TurnBuffer(), busy = false, continuous = false, pageIndex = 0, disposed = false, locatedRow = null;
      const collapsedTurns = new Set();
      const expandedRows = new Set();
      const warningSet = new Set();
      const localAbort = new AbortController();
      const signal = localAbort.signal;
      const showTimingResults = createScrollableResults(timingList, "耗时定位结果", 5, signal);
      const showToolResults = createScrollableResults(toolsList, "工具失败与重试结果", 6, signal);
      context.signal.addEventListener("abort", () => localAbort.abort(), {once:true, signal});
      const imageCache = new Map(), objectURLs = new Set();
      const comparisonCache = new Map();
      const childRequests = new Map(), childViews = new Map(), invocations = new Map();
      let childGeneration = 0, childAbort = new AbortController(), activeChildRequests = 0;
      const childQueue = [];
      signal.addEventListener("abort", () => {
        childAbort.abort(); childRequests.clear(); childViews.clear(); invocations.clear();
      }, {once:true});
      function pumpChildRequests() {
        while (activeChildRequests < 2 && childQueue.length) {
          const work = childQueue.shift();
          activeChildRequests++;
          void work().finally(() => {activeChildRequests--; pumpChildRequests();});
        }
      }
      function childJSON(route, cursor) {
        const key = `${route}:${cursor}`;
        if (!childRequests.has(key)) {
          const requestSignal = childAbort.signal;
          const promise = new Promise((resolve, reject) => {
            childQueue.push(async () => {
              try {
                requestSignal.throwIfAborted();
                const url = gatewayURL(`/api/ext-trajectory/threads/${encodeURIComponent(threadId)}/${route}`);
                url.searchParams.set("cursor", cursor);
                const response = await fetch(url, {credentials:"include", signal:requestSignal});
                const data = await response.json();
                if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
                resolve(data);
              } catch (error) {reject(error);}
            });
            pumpChildRequests();
          }).catch(error => {
            if (childRequests.get(key) === promise) childRequests.delete(key);
            throw error;
          });
          childRequests.set(key, promise);
        }
        return childRequests.get(key);
      }
      function invocationState(call) {
        if (!invocations.has(call.subagent_cursor)) invocations.set(call.subagent_cursor, {children:null, warnings:[], busy:false, error:null});
        return invocations.get(call.subagent_cursor);
      }
      function childState(child) {
        if (!childViews.has(child.cursor)) childViews.set(child.cursor, {rows:[], cursor:child.cursor, warnings:new Set(), busy:false, loaded:false, error:null});
        return childViews.get(child.cursor);
      }
      async function loadChildren(call) {
        const state = invocationState(call), generation = childGeneration;
        if (state.busy || state.children !== null || signal.aborted) return;
        state.busy = true; state.error = null;
        try {
          const data = await childJSON("subagents", call.subagent_cursor);
          if (signal.aborted || generation !== childGeneration) return;
          state.children = data.children; state.warnings = data.warnings || [];
        } catch (error) {
          if (!signal.aborted && generation === childGeneration) state.error = error.message;
        } finally {
          state.busy = false;
          if (!signal.aborted && generation === childGeneration) render();
        }
      }
      async function loadChild(child) {
        const state = childState(child), generation = childGeneration;
        if (state.busy || !state.cursor || signal.aborted) return;
        state.busy = true; state.error = null;
        let scanned = 0, count = 0;
        try {
          do {
            const page = await childJSON("subagent-checkpoints", state.cursor);
            if (signal.aborted || generation !== childGeneration) return;
            const seen = new Set(state.rows.map(row => row.row_id));
            state.rows = [...page.rows.filter(row => !seen.has(row.row_id)), ...state.rows];
            state.cursor = page.next_cursor;
            for (const warning of page.warnings || []) state.warnings.add(warning);
            scanned += page.scanned || 0; count++;
          } while (state.cursor && scanned < 1000 && state.rows.length < 200 && count < 50);
        } catch (error) {
          if (!signal.aborted && generation === childGeneration) state.error = error.message;
        } finally {
          state.busy = false; state.loaded = true;
          if (!signal.aborted && generation === childGeneration) render();
        }
      }
      function timelineEntries(visibleRows) {
        const entries = [];
        for (const parent of visibleRows) {
          entries.push({type:"row", row:parent, parent});
          for (const call of parent.tool_calls || []) {
            if (call.name !== "task" || !call.subagent_cursor) continue;
            const invocation = invocationState(call);
            if (invocation.children === null || !invocation.children.length || invocation.warnings.length) entries.push({type:"invocation", parent, call, state:invocation});
            for (const child of invocation.children || []) {
              const state = childState(child);
              const source = {name:child.name, execution_id:child.execution_id, tool_call_id:call.id, parent_row_id:parent.row_id};
              const names = new Map();
              for (const row of state.rows) for (const tool of row.tool_calls || []) if (tool.id) names.set(tool.id, tool.name);
              entries.push({type:"child-heading", parent, child});
              for (const row of state.rows) entries.push({type:"row", parent, names, row:{...row, subagent_source:source}});
              if (!state.rows.length || state.cursor || state.error || state.warnings.size) entries.push({type:"child-status", parent, child, state});
            }
          }
        }
        return entries;
      }
      function childStatus(entry, parent, jobs) {
        const item = element("li", undefined, parent);
        item.className = "trajectory-child-status";
        const state = entry.state;
        if (entry.type === "invocation") {
          for (const warning of state.warnings) element("p", warning, item);
          if (state.error) {
            element("p", `子执行查找失败：${state.error}`, item);
            element("button", "重试查找子轨迹", item).addEventListener("click", () => {void loadChildren(entry.call); render();}, {signal});
          } else if (state.children === null) {
            item.textContent = "正在查找子 agent 轨迹…";
            if (!state.busy) jobs.push(() => loadChildren(entry.call));
          } else if (!state.children.length) element("p", "没有找到已保存的子轨迹。可能运行时未启用子任务持久化，或历史已被清理。", item);
        } else {
          item.setAttribute("data-execution-id", entry.child.execution_id);
          for (const warning of state.warnings) element("p", warning, item);
          if (state.error) element("p", `子轨迹读取失败：${state.error}`, item);
          else if (state.busy || !state.loaded) element("p", "正在读取子 agent 步骤…", item);
          else if (!state.rows.length && state.cursor) element("p", "暂未读到可展示的子步骤，可以加载更早记录。", item);
          else if (!state.rows.length) element("p", "没有可展示的子任务消息。", item);
          if (state.cursor) {
            const more = element("button", state.error ? "重试读取子轨迹" : "加载更早子步骤", item);
            more.disabled = state.busy;
            more.addEventListener("click", () => {void loadChild(entry.child); render();}, {signal});
            if (!state.loaded && !state.busy && !state.error) jobs.push(() => loadChild(entry.child));
          }
        }
      }
      signal.addEventListener("abort", () => comparisonCache.clear(), {once:true});
      function addComparison(body, box, row) {
        const container = element("div", undefined, body);
        container.className = "trajectory-comparison";
        let loading = false, loaded = false;
        async function loadComparison() {
          if (loading || loaded || signal.aborted) return;
          loading = true;
          container.replaceChildren();
          element("p", "正在读取完整的压缩前后内容…", container);
          try {
            if (!row.comparison_cursor) throw new Error("请刷新轨迹页以获取压缩对照");
            let promise = comparisonCache.get(row.comparison_cursor);
            if (!promise) {
              const url = gatewayURL(`/api/ext-trajectory/threads/${encodeURIComponent(threadId)}/compaction`);
              url.searchParams.set("cursor", row.comparison_cursor);
              promise = fetch(url, {credentials:"include", signal}).then(async response => {
                const data = await response.json();
                if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
                return data;
              });
              comparisonCache.set(row.comparison_cursor, promise);
            }
            const data = await promise;
            if (signal.aborted) return;
            renderComparison(container, data);
            loaded = true;
          } catch (error) {
            comparisonCache.delete(row.comparison_cursor);
            if (signal.aborted) return;
            container.replaceChildren();
            element("p", `压缩对照读取失败：${error.message}`, container);
            element("button", "重试读取对照", container).addEventListener("click", () => void loadComparison(), {signal});
          } finally {loading = false;}
        }
        box.addEventListener("toggle", () => {if (box.open) void loadComparison();}, {signal});
        if (box.open) void loadComparison();
      }
      let exporting = false, downloadURL;
      async function download(format) {
        if (exporting || !threadId) return;
        exporting = true;
        exportMarkdown.disabled = exportJSON.disabled = true;
        exportMenu.open = false;
        exportStatus.textContent = "正在读取整个对话并生成导出文件…";
        try {
          const url = gatewayURL(`/api/ext-trajectory/threads/${encodeURIComponent(threadId)}/export`);
          url.searchParams.set("format", format);
          if (thresholdOverrides.size) url.searchParams.set("slow_thresholds_ms", JSON.stringify(Object.fromEntries(thresholdOverrides)));
          const response = await fetch(url, {credentials:"include", signal});
          if (!response.ok) {
            const detail = await response.json().catch(() => ({}));
            throw new Error(typeof detail.detail === "string" ? detail.detail : `导出失败（${response.status}）`);
          }
          const blob = await response.blob();
          signal.throwIfAborted();
          if (downloadURL) {URL.revokeObjectURL(downloadURL); objectURLs.delete(downloadURL);}
          downloadURL = URL.createObjectURL(blob);
          objectURLs.add(downloadURL);
          const link = element("a", undefined, shell);
          link.href = downloadURL;
          link.download = `trajectory-${threadId}.${format === "json" ? "json" : "zip"}`;
          link.hidden = true;
          link.click();
          link.remove();
          const count = Number(response.headers.get("X-Trajectory-Warnings")) || 0;
          exportStatus.textContent = count ? `导出含 ${count} 项提示，请查看文件中的导出说明。` : "";
        } catch (error) {
          if (!signal.aborted) exportStatus.textContent = `导出未完成：${error.message}`;
        } finally {
          exporting = false;
          exportMarkdown.disabled = exportJSON.disabled = false;
        }
      }
      exportMarkdown.addEventListener("click", () => download("markdown"), {signal});
      exportJSON.addEventListener("click", () => download("json"), {signal});
      signal.addEventListener("abort", () => {
        for (const url of objectURLs) URL.revokeObjectURL(url);
        objectURLs.clear(); imageCache.clear();
      }, {once:true});
      const lightbox = element("dialog", undefined, shell);
      const closeImage = element("button", "关闭预览", lightbox);
      const largeImage = element("img", undefined, lightbox);
      closeImage.addEventListener("click", () => lightbox.close(), {signal});
      lightbox.addEventListener("click", event => {if (event.target === lightbox) lightbox.close();}, {signal});
      async function imageURL(path) {
        if (imageCache.has(path)) return imageCache.get(path);
        const pending = (async () => {
          const response = await fetch(imageEndpoint(threadId, path), {credentials:"include", signal});
          if (!response.ok) throw new Error(response.status === 404 ? "图片已不存在" : `图片无法读取（${response.status}）`);
          if (!/^image\/(png|jpeg|webp|gif)(;|$)/i.test(response.headers.get("content-type") || "")) throw new Error("文件不是支持预览的图片");
          const cap = 20 * 1024 * 1024;
          if (Number(response.headers.get("content-length")) > cap) {await response.body?.cancel(); throw new Error("图片超过 20 MB，暂不预览");}
          const reader = response.body.getReader(), chunks = [];
          let size = 0;
          try {
            while (true) {
              const {done, value} = await reader.read();
              if (done) break;
              size += value.byteLength;
              if (size > cap) {await reader.cancel(); throw new Error("图片超过 20 MB，暂不预览");}
              chunks.push(value);
            }
          } finally {reader.releaseLock();}
          signal.throwIfAborted();
          const url = URL.createObjectURL(new Blob(chunks, {type:response.headers.get("content-type")}));
          objectURLs.add(url);
          return url;
        })();
        imageCache.set(path, pending);
        try {return await pending;} catch (error) {imageCache.delete(path); throw error;}
      }
      function addImages(body, box, images) {
        const gallery = element("div", undefined, body);
        gallery.className = "trajectory-images";
        for (const image of images) {
          const card = element("button", undefined, gallery);
          card.className = "trajectory-image-card";
          card.type = "button";
          const thumbnail = element("img", undefined, card);
          thumbnail.alt = image.name;
          thumbnail.hidden = true;
          const caption = element("span", `${image.name} · ${image.size}`, card);
          let url, loading = false;
          async function loadImage() {
            if (url || loading || signal.aborted) return;
            loading = true;
            caption.textContent = `${image.name} · 加载中…`;
            try {
              url = await imageURL(image.path);
              if (signal.aborted) return;
              thumbnail.src = url; thumbnail.hidden = false;
              caption.textContent = `${image.name} · ${image.size} · 点击放大`;
            } catch (error) {if (!signal.aborted) caption.textContent = `${image.name} · ${error.message}，点击重试`;}
            finally {loading = false;}
          }
          box.addEventListener("toggle", () => {if (box.open) void loadImage();});
          if (box.open) void loadImage();
          card.addEventListener("click", async () => {
            await loadImage();
            if (!url || signal.aborted) return;
            largeImage.src = url; largeImage.alt = image.name;
            if (!lightbox.open) lightbox.showModal();
          });
        }
      }
      function render() {
        const names = new Map();
        const turns = new Map();
        let turn = 0;
        const turnCount = rows.filter(row => row.kind === "user" && !row.updated).length;
        let currentTurn = {id:"leading-history", label:"较早轮次（续）", firstRow:null};
        for (const row of rows) {
          if (row.kind === "user" && !row.updated) {
            turn++;
            currentTurn = {
              id:row.row_id,
              label:!buffer.hasMore ? `第${turn}轮` : (turn === turnCount ? "最新一轮" : `倒数第${turnCount - turn + 1}轮`),
              firstRow:row.row_id,
            };
          }
          turns.set(row.row_id, currentTurn);
          for (const call of row.tool_calls || []) if (call.id) names.set(call.id, call.name);
        }
        // Keep empty user messages above as turn boundaries, but omit empty cards.
        const visibleRows = rows.filter(row => (row.display_text ?? row.text ?? "").trim() || row.images?.length || row.tool_calls?.length || row.tool_status || row.kind === "compaction" || row.kind === "state_change");
        const visibleIds = new Set(visibleRows.map(row=>row.row_id));
        const rawEntries = timelineEntries(rows);
        const analyzed = new Map(analyzeRows(rawEntries.filter(entry=>entry.type==="row").map(entry=>entry.row),threadId).map(row=>[row.row_id,row]));
        const entries = rawEntries.filter(entry=>entry.type!=="row" || visibleIds.has(entry.row.row_id) || entry.row.subagent_source).map(entry => {
          if (entry.type !== "row") return entry;
          const row = analyzed.get(entry.row.row_id);
          row.timing = applyThreshold(row.timing, thresholdOverrides);
          return {...entry, row};
        });
        function locateEntry(entry) {
          pageIndex=Math.floor(entries.indexOf(entry)/100);
          locatedRow=entry.row.row_id; expandedRows.add(locatedRow);
          collapsedTurns.delete(turns.get(entry.parent.row_id).id);
          render();
          const target=Array.from(list.querySelectorAll?.("[data-row-id]") || []).find(node=>node.getAttribute("data-row-id")===locatedRow);
          target?.scrollIntoView?.({block:"center",behavior:window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? "auto" : "smooth"}); target?.querySelector?.("summary")?.focus();
        }
        const entryById=new Map(entries.filter(entry=>entry.type==="row").map(entry=>[entry.row.row_id,entry]));
        const findings=toolFindings([...analyzed.values()]);
        const failures=findings.filter(item=>item.kind==="failure" && item.confidence==="observed").length;
        const suspected=findings.filter(item=>item.kind==="failure" && item.confidence!=="observed").length;
        toolsStats.textContent=`${failures} 项失败${suspected ? ` · ${suspected} 项待核对` : ""} · ${findings.filter(item=>item.kind==="retry").length} 项重试线索`;
        const selected=findings.filter(item=>toolsFilter.value==="failure" ? item.kind==="failure" : toolsFilter.value==="repeat" ? item.kind==="retry" && item.retry_kind==="same_call_after_failure" : toolsFilter.value==="possible" ? item.kind==="retry" && item.confidence!=="observed" : true);
        showToolResults(selected.filter(finding => entryById.has(finding.row_id)), finding => {
          const entry=entryById.get(finding.row_id);
          const source=entry.row.subagent_source ? `子 agent ${entry.row.subagent_source.name} · ` : "";
          const category=finding.kind==="failure" ? (finding.confidence==="observed" ? "失败" : "待核对") : (finding.confidence==="observed" ? `失败后相同调用（第 ${finding.repeat_index} 次）` : "可能重试");
          const item=element("li",undefined,toolsList);
          const button=element("button",`定位：${source}${finding.name} · ${category} · ${finding.reason}`,item);
          button.addEventListener("click",()=>locateEntry(entry));
        }, "当前已加载记录中没有符合条件的工具失败或重试线索。");
        const candidates = entries.filter(entry => entry.type === "row" && ["assistant","tool","timing"].includes(entry.row.kind));
        const measured = new Map();
        for (const entry of candidates) if (measuredDuration(entry.row.timing) !== null) measured.set(entry.row.timing.span_id || entry.row.row_id, entry);
        timingStats.textContent = `${measured.size} 项已记录 / ${candidates.filter(entry => measuredDuration(entry.row.timing) === null).length} 项未记录`;
        const ranked = [...measured.values()].filter(entry => timingFilter.value === "slow" ? entry.row.timing.is_slow : timingFilter.value === "failed" ? ["failed","timeout"].includes(entry.row.timing.outcome) : true).sort((a,b) => measuredDuration(b.row.timing) - measuredDuration(a.row.timing));
        const noTimingResults = timingFilter.value === "slow" ? "当前没有超过已配置阈值的步骤；未配置阈值的操作不会标慢。" : timingFilter.value === "failed" ? "已记录计时的步骤中，没有失败或超时。" : "当前范围没有已记录的计时。";
        showTimingResults(ranked, entry => {
          const timing = entry.row.timing;
          const source = entry.row.subagent_source ? `子 agent ${entry.row.subagent_source.name} · ` : "";
          const label = `${source}${timing.operation === "model" ? "模型完整响应" : "工具"} · ${timing.name} · ${durationLabel(timing)}${timing.is_slow ? " · 慢" : ""} · ${outcomes[timing.outcome] || timing.outcome}`;
          const item = element("li", undefined, timingList);
          const locate = element("button", `定位：${label}`, item);
          locate.addEventListener("click", () => locateEntry(entry));
        }, noTimingResults);
        const pageCount = Math.max(1, Math.ceil(entries.length / 100));
        pageIndex = Math.min(pageIndex, pageCount - 1);
        const groups = [], jobs = [], groupCounts = new Map();
        for (const entry of entries) if (entry.type === "row") {
          const id = turns.get(entry.parent.row_id).id;
          groupCounts.set(id, (groupCounts.get(id) || 0) + 1);
        }
        let groupId = null, groupRows;
        for (const entry of entries.slice(pageIndex * 100, (pageIndex + 1) * 100)) {
          const group = turns.get(entry.parent.row_id);
          if (group.id !== groupId) {
            groupId = group.id;
            const section = element("li");
            section.className = "trajectory-turn";
            const fold = element("details", undefined, section);
            fold.open = !collapsedTurns.has(group.id);
            const continuation = entries.slice(0, pageIndex * 100).some(previous => turns.get(previous.parent.row_id).id === group.id) ? "（续）" : "";
            const turnTitle = element("summary", group.label + continuation, fold);
            turnTitle.className = "trajectory-turn-title";
            element("span", `${groupCounts.get(group.id) || 0} 个步骤`, turnTitle).className = "trajectory-turn-count";
            groupRows = element("ol", undefined, fold);
            groupRows.className = "trajectory-turn-rows";
            fold.addEventListener("toggle", () => {
              if (!fold.isConnected) return;
              if (fold.open) collapsedTurns.delete(group.id);
              else collapsedTurns.add(group.id);
            });
            groups.push(section);
          }
          if (entry.type === "row") {
            const item = rowView(entry.row, context.locale, entry.names || names, expandedRows, addImages, addComparison);
            if (entry.row.row_id === locatedRow) item.className += " trajectory-located";
            groupRows.append(item);
          }
          else if (entry.type === "child-heading") {
            const heading = element("li", undefined, groupRows);
            heading.className = "trajectory-child-heading";
            heading.setAttribute("data-execution-id", entry.child.execution_id);
            element("strong", `子 agent · ${entry.child.name}`, heading);
          } else childStatus(entry, groupRows, jobs);
        }
        list.replaceChildren(...groups);
        pageLabel.textContent = `第 ${pageIndex + 1} / ${pageCount} 页`;
        previous.disabled = pageIndex === 0;
        next.disabled = pageIndex >= pageCount - 1;
        pagination.hidden = pageCount <= 1;
        status.textContent = "";
        warnings.textContent = [...warningSet].join(" ");
        for (const job of jobs) void job();
      }
      async function load(mode = "turn") {
        if (busy || !buffer.hasMore || !threadId || disposed) return;
        busy = true;
        continuous = true;
        refresh.disabled = older.disabled = true;
        all.disabled = false;
        all.textContent = "暂停读取";
        status.textContent = "正在读取这一轮…";
        let scannedThisLoad = 0;
        try {
          while (continuous && !disposed && !signal.aborted && buffer.hasMore) {
            const turnRows = buffer.takeTurn();
            if (turnRows) {
              rows = [...turnRows, ...rows];
              pageIndex = 0;
              render();
              if (mode === "turn") break;
            } else {
              const response = await fetch(endpoint(threadId, buffer.cursor), {credentials:"include", signal});
              const data = await response.json();
              if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
              if (disposed || signal.aborted) return;
              for (const [operation, input] of thresholdInputs) {
                const threshold = data.slow_threshold_defaults_ms?.[operation];
                input.placeholder = validThreshold(threshold) ? String(threshold / 1000) : "默认无限制";
              }
              buffer.add(data);
              scannedThisLoad += data.scanned || 0;
              for (const warning of data.warnings || []) warningSet.add(warning);
            }
            if (scannedThisLoad >= 10000 || (mode === "all" && rows.length >= 10000)) {
              warningSet.add("历史较多，已暂停自动读取；可继续手动加载。尚未读到起点的轮次会在读取完成后显示。");
              break;
            }
          }
          render();
          if (!rows.length && !buffer.hasMore) status.textContent = "暂无可读取的轨迹。";
        } catch (error) {
          if (!signal.aborted) status.textContent = `读取失败：${error.message}`;
        } finally {
          busy = false;
          continuous = false;
          refresh.disabled = false;
          older.disabled = !buffer.hasMore;
          all.disabled = !buffer.hasMore;
          all.textContent = "读取整个对话";
        }
      }
      older.addEventListener("click", () => void load(), {signal});
      all.addEventListener("click", () => {
        if (busy) {continuous = false; all.disabled = true; all.textContent = "正在暂停…";}
        else void load("all");
      }, {signal});
      refresh.addEventListener("click", () => {
        if (busy) return;
        timingList.scrollTop = toolsList.scrollTop = 0;
        rows = []; buffer = new TurnBuffer(); pageIndex = 0; warningSet.clear(); collapsedTurns.clear(); expandedRows.clear(); comparisonCache.clear();
        locatedRow = null;
        childGeneration++; childAbort.abort(); childAbort = new AbortController();
        childRequests.clear(); childViews.clear(); invocations.clear();
        list.replaceChildren(); void load();
      }, {signal});
      function changePage(offset) {
        pageIndex += offset;
        render();
        const title = list.querySelector?.(".trajectory-turn-title");
        title?.focus({preventScroll:true});
        title?.scrollIntoView({block:"start"});
      }
      previous.addEventListener("click", () => changePage(-1), {signal});
      next.addEventListener("click", () => changePage(1), {signal});
      if (threadId) void load();
      else {status.textContent = "请从对话菜单打开运行轨迹。"; older.disabled = all.disabled = refresh.disabled = true;}
      return {dispose() {disposed = true; continuous = false; localAbort.abort(); root.replaceChildren();}};
    },
  }],
  conversationActions(_t, locale = "en") {
    const zh = locale.startsWith("zh");
    return {label:zh ? "运行轨迹" : "Trajectory", icon:"file-text", actions:[{
      id:"open-trajectory", label:zh ? "查看本对话轨迹" : "View this conversation's trajectory", icon:"file-text",
      available:settings => settings.enabled === true,
      execute(context) {window.location.assign(`/workspace/extensions/community.trajectory/viewer?thread_id=${encodeURIComponent(context.thread.thread_id)}`);},
    }]};
  },
};
