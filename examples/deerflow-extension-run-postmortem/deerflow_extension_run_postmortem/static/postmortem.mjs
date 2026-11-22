/**
 * Run postmortem page.
 *
 * Renders one sealed run's evidence report and downloads its Markdown form.
 * All data crosses the host's authenticated action bridge (`context.callBackend`);
 * this module holds no credentials and no network code of its own.
 */

const WORDS = {
  en: {
    title: "Run postmortem",
    intro:
      "Explain one finished run from its sealed evidence. Reports are owner-scoped.",
    thread: "Thread ID",
    run: "Run ID",
    maxEvents: "Max events",
    latest: "Latest run",
    generate: "Generate report",
    loading: "Reading evidence…",
    missing: "Enter a thread and run ID, or load the latest run.",
    notFound: "No run of yours was found for that thread and run ID.",
    noRun: "This thread has no runs you own.",
    latestFound: "Latest run",
    scanIncomplete: (scanned) =>
      `Scanned ${scanned} run records without reaching the end; the newest run could not be confirmed. Enter the run ID manually.`,
    showing: (shown, total) => `Showing ${shown} of ${total} events`,
    showMore: (count) => `Show ${count} more events`,
    verdict: "Verdict",
    anomalies: "Anomalies",
    none: "None detected in the retained evidence.",
    activity: "Activity",
    timeline: "Timeline",
    caveats: "Evidence caveats",
    download: "Download Markdown",
    downloaded: "Report downloaded.",
    failed: "Could not build the report. Check the IDs and try again.",
    truncated: "(truncated)",
    messages: "Messages",
    toolFailures: "Tool failures",
    subagents: "Subagents",
    delivery: "Delivery",
    events: "Events",
    status: "Status",
    stopReason: "Stop reason",
    seal: "Evidence",
    agent: "Agent",
    origin: "Origin",
    seq: "#",
    event: "Event",
    summary: "Summary",
  },
  zh: {
    title: "运行复盘",
    intro: "用一次已封存运行的事件证据解释它发生了什么。报告仅限运行所有者查看。",
    thread: "会话 ID",
    run: "运行 ID",
    maxEvents: "最多事件数",
    latest: "最新一次运行",
    generate: "生成报告",
    loading: "正在读取证据…",
    missing: "请填写会话与运行 ID，或先获取最新一次运行。",
    notFound: "没有找到属于你的这次运行。",
    noRun: "该会话下没有属于你的运行。",
    latestFound: "最新运行",
    scanIncomplete: (scanned) =>
      `只扫描了 ${scanned} 条运行记录，未到末尾，无法确认最新一次；请手动填写运行 ID。`,
    showing: (shown, total) => `已显示 ${shown} / ${total} 条事件`,
    showMore: (count) => `再显示 ${count} 条`,
    verdict: "结论",
    anomalies: "异常",
    none: "在保留的证据中未发现异常。",
    activity: "活动",
    timeline: "时间线",
    caveats: "证据覆盖说明",
    download: "下载 Markdown",
    downloaded: "报告已下载。",
    failed: "无法生成报告，请检查 ID 后重试。",
    truncated: "（已截断）",
    messages: "消息",
    toolFailures: "工具失败",
    subagents: "子代理",
    delivery: "交付",
    events: "事件数",
    status: "状态",
    stopReason: "停止原因",
    seal: "证据",
    agent: "智能体",
    origin: "来源",
    seq: "序号",
    event: "事件",
    summary: "摘要",
  },
};

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else node.setAttribute(key, String(value));
  }
  for (const child of children) {
    if (child) node.append(child);
  }
  return node;
}

function styleSheet() {
  return `
.pm-page { display: flex; flex-direction: column; gap: 16px; padding: 4px 0; max-width: 1080px; }
.pm-page h2 { margin: 0; font-size: 20px; }
.pm-page p { margin: 0; }
.pm-intro { opacity: .72; }
.pm-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; align-items: end; }
.pm-field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.pm-field input { padding: 7px 9px; border: 1px solid color-mix(in srgb, currentColor 24%, transparent); border-radius: 7px; background: transparent; color: inherit; }
.pm-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.pm-page button { padding: 7px 12px; border-radius: 7px; border: 1px solid color-mix(in srgb, currentColor 28%, transparent); background: transparent; color: inherit; cursor: pointer; }
.pm-page button.pm-primary { background: color-mix(in srgb, currentColor 12%, transparent); font-weight: 600; }
.pm-page button:disabled { opacity: .5; cursor: default; }
.pm-status { opacity: .78; }
.pm-error { color: #b42318; }
.pm-report { display: flex; flex-direction: column; gap: 14px; }
.pm-verdict { font-size: 16px; font-weight: 600; }
.pm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }
.pm-card { border: 1px solid color-mix(in srgb, currentColor 16%, transparent); border-radius: 9px; padding: 9px 11px; }
.pm-card dt { font-size: 12px; opacity: .7; }
.pm-card dd { margin: 3px 0 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.pm-page h3 { margin: 6px 0 0; font-size: 15px; }
.pm-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; }
.pm-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; opacity: .85; }
.pm-timeline { overflow: auto; max-height: 460px; border: 1px solid color-mix(in srgb, currentColor 16%, transparent); border-radius: 9px; }
.pm-timeline table { border-collapse: collapse; width: 100%; font-size: 13px; }
.pm-timeline th, .pm-timeline td { text-align: left; padding: 6px 9px; border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent); vertical-align: top; }
.pm-timeline th { position: sticky; top: 0; background: color-mix(in srgb, currentColor 6%, Canvas); }
.pm-timeline td.pm-seq { font-variant-numeric: tabular-nums; opacity: .7; white-space: nowrap; }
.pm-timeline td.pm-type { white-space: nowrap; }
`;
}

export function mount(root, context) {
  const zh = String(context.locale || "en").startsWith("zh");
  const t = zh ? WORDS.zh : WORDS.en;
  let disposed = false;
  let pending = null;
  let timelineEntries = [];
  let renderedRows = 0;
  let timelineBody = null;
  let timelineFooter = null;
  let showMoreButton = null;
  const TIMELINE_CHUNK = 400;

  const alive = () => !disposed && !context.signal.aborted;

  const style = el("style");
  style.textContent = styleSheet();
  const page = el("section", { class: "pm-page", "aria-label": t.title });

  const threadInput = el("input", {
    type: "text",
    maxlength: "256",
    placeholder: "00000000-0000-0000-0000-000000000000",
    "aria-label": t.thread,
  });
  const runInput = el("input", {
    type: "text",
    maxlength: "256",
    placeholder: "run id",
    "aria-label": t.run,
  });
  const maxInput = el("input", {
    type: "number",
    min: "1",
    max: "2000",
    step: "1",
    value: "200",
    "aria-label": t.maxEvents,
  });
  // Hosts that mount a page without thread context omit threadId; the field
  // stays empty and editable so the operator can type it.
  if (context.threadId) threadInput.value = context.threadId;

  const latestButton = el("button", {
    type: "button",
    text: t.latest,
    "aria-label": t.latest,
  });
  const generateButton = el("button", {
    type: "submit",
    class: "pm-primary",
    text: t.generate,
  });
  const statusLine = el("p", { class: "pm-status", role: "status" });
  const errorLine = el("p", { class: "pm-error", role: "alert" });

  const report = el("div", { class: "pm-report", hidden: "hidden" });
  const verdict = el("p", { class: "pm-verdict" });
  const overview = el("div", { class: "pm-grid" });
  const anomalies = el("ul", { class: "pm-list" });
  const activity = el("ul", { class: "pm-list" });
  const timeline = el("div", { class: "pm-timeline" });
  const caveats = el("ul", { class: "pm-list" });
  const downloadButton = el("button", {
    type: "button",
    text: t.download,
    disabled: "disabled",
  });

  const form = el("form", { class: "pm-form" }, [
    el("label", { class: "pm-field" }, [el("span", { text: t.thread }), threadInput]),
    el("label", { class: "pm-field" }, [el("span", { text: t.run }), runInput]),
    el("label", { class: "pm-field" }, [el("span", { text: t.maxEvents }), maxInput]),
    el("div", { class: "pm-actions" }, [latestButton, generateButton]),
  ]);

  page.append(
    el("h2", { text: t.title }),
    el("p", { class: "pm-intro", text: t.intro }),
    form,
    statusLine,
    errorLine,
    report,
  );
  report.append(
    verdict,
    overview,
    el("h3", { text: t.anomalies }),
    anomalies,
    el("h3", { text: t.activity }),
    activity,
    el("h3", { text: t.timeline }),
    timeline,
    el("h3", { text: t.caveats }),
    caveats,
    el("div", { class: "pm-actions" }, [downloadButton]),
  );
  root.replaceChildren(style, page);

  const setStatus = (text) => {
    statusLine.textContent = text || "";
  };
  const setError = (text) => {
    errorLine.textContent = text || "";
  };
  const setBusy = (busy) => {
    latestButton.disabled = busy;
    generateButton.disabled = busy;
    downloadButton.disabled = busy || !pending;
  };
  const payloadFor = () => {
    const parsed = Number.parseInt(maxInput.value, 10);
    const max = Number.isFinite(parsed) ? Math.min(2000, Math.max(1, parsed)) : 200;
    return {
      thread_id: threadInput.value.trim(),
      run_id: runInput.value.trim(),
      max_events: max,
    };
  };

  const card = (term, value) =>
    el("dl", { class: "pm-card" }, [el("dt", { text: term }), el("dd", { text: value })]);

  const renderTimelineChunk = () => {
    if (!timelineBody) return;
    const next = timelineEntries.slice(renderedRows, renderedRows + TIMELINE_CHUNK);
    for (const entry of next) {
      timelineBody.append(
        el("tr", {}, [
          el("td", { class: "pm-seq", text: String(entry.seq ?? "") }),
          el("td", { class: "pm-type" }, [
            el("span", { class: "pm-code", text: entry.event_type || "" }),
          ]),
          el("td", {
            text: `${entry.summary || ""}${entry.truncated ? ` ${t.truncated}` : ""}`,
          }),
        ]),
      );
    }
    renderedRows += next.length;
    const remaining = timelineEntries.length - renderedRows;
    timelineFooter.textContent = t.showing(renderedRows, timelineEntries.length);
    showMoreButton.hidden = remaining <= 0;
    if (remaining > 0) {
      showMoreButton.textContent = t.showMore(Math.min(TIMELINE_CHUNK, remaining));
    }
  };

  const renderReport = (data) => {
    report.hidden = false;
    verdict.textContent = data.verdict || "";
    overview.replaceChildren(
      card(t.status, data.status || "-"),
      card(t.stopReason, data.stop_reason || "-"),
      card(t.seal, `${data.seal_state || "-"} (${data.events_read}/${data.events_total})`),
      card(t.agent, data.agent_id || "-"),
      card(t.origin, data.origin || "-"),
      card(
        t.messages,
        `${data.message_counts?.user ?? 0} / ${data.message_counts?.assistant ?? 0} / ${data.message_counts?.tool_results ?? 0}`,
      ),
      card(t.toolFailures, String(data.tool_failures ?? 0)),
      card(
        t.subagents,
        `${data.subagents?.started ?? 0} / ${data.subagents?.ended ?? 0}`,
      ),
    );
    const delivery = data.delivery || {};
    if (delivery.satisfied !== null && delivery.satisfied !== undefined) {
      overview.append(
        card(
          t.delivery,
          `${delivery.satisfied} (${delivery.presented ?? 0}/${delivery.produced ?? 0})`,
        ),
      );
    }
    anomalies.replaceChildren();
    const items = Array.isArray(data.anomalies) ? data.anomalies : [];
    if (items.length === 0) {
      anomalies.append(el("li", { text: t.none }));
    } else {
      for (const anomaly of items) {
        anomalies.append(
          el("li", {}, [
            el("span", { class: "pm-code", text: anomaly.code || "anomaly" }),
            el("span", { text: ` — ${anomaly.detail || ""}` }),
          ]),
        );
      }
    }
    activity.replaceChildren(
      el("li", {
        text: `${t.events}: ${data.events_read ?? 0}/${data.events_total ?? 0}`,
      }),
    );
    timelineEntries = Array.isArray(data.timeline) ? data.timeline : [];
    renderedRows = 0;
    timelineBody = el("tbody");
    timelineFooter = el("p", { class: "pm-status" });
    showMoreButton = el("button", {
      type: "button",
      text: t.showMore(TIMELINE_CHUNK),
    });
    showMoreButton.addEventListener("click", () => renderTimelineChunk());
    timeline.replaceChildren(
      el("table", {}, [
        el("tr", {}, [
          el("th", { text: t.seq }),
          el("th", { text: t.event }),
          el("th", { text: t.summary }),
        ]),
        timelineBody,
      ]),
      el("div", { class: "pm-actions" }, [showMoreButton, timelineFooter]),
    );
    renderTimelineChunk();
    caveats.replaceChildren(
      ...(Array.isArray(data.caveats) ? data.caveats : []).map((item) =>
        el("li", { text: item }),
      ),
    );
  };

  const clearReport = () => {
    report.hidden = true;
    pending = null;
    timelineEntries = [];
    renderedRows = 0;
    setBusy(false);
  };

  const generate = async () => {
    const payload = payloadFor();
    if (!payload.thread_id || !payload.run_id) {
      setStatus(t.missing);
      setError("");
      return;
    }
    setError("");
    setStatus(t.loading);
    setBusy(true);
    try {
      const data = await context.callBackend("report", payload);
      if (!alive()) return;
      if (!data || data.not_found) {
        clearReport();
        setStatus(t.notFound);
        return;
      }
      pending = payload;
      renderReport(data);
      setStatus("");
      setBusy(false);
    } catch {
      if (!alive()) return;
      clearReport();
      setError(t.failed);
      setStatus("");
    }
  };

  const loadLatest = async () => {
    const threadId = threadInput.value.trim();
    if (!threadId) {
      setStatus(t.missing);
      return;
    }
    setError("");
    setStatus(t.loading);
    setBusy(true);
    try {
      const data = await context.callBackend("latest", { thread_id: threadId });
      if (!alive()) return;
      if (!data || data.complete === false) {
        runInput.value = "";
        setStatus(t.scanIncomplete(data && data.scanned ? data.scanned : 0));
        return;
      }
      const run = data.run;
      if (!run) {
        setStatus(t.noRun);
        return;
      }
      runInput.value = run.run_id || "";
      setStatus(`${t.latestFound}: ${run.run_id} (${run.status})`);
    } catch {
      if (!alive()) return;
      setError(t.failed);
    } finally {
      if (alive()) setBusy(false);
    }
  };

  const download = async () => {
    if (!pending) return;
    setError("");
    setBusy(true);
    try {
      const data = await context.callBackend("markdown", pending);
      if (!alive()) return;
      if (!data || data.not_found) {
        setError(t.notFound);
        return;
      }
      const blob = new Blob([data.markdown || ""], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const anchor = el("a", {
        href: url,
        download: data.filename || "postmortem.md",
      });
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setStatus(t.downloaded);
    } catch {
      if (alive()) setError(t.failed);
    } finally {
      if (alive()) setBusy(false);
    }
  };

  const onSubmit = (event) => {
    event.preventDefault();
    void generate();
  };
  form.addEventListener("submit", onSubmit);
  latestButton.addEventListener("click", () => void loadLatest());
  downloadButton.addEventListener("click", () => void download());

  return {
    dispose() {
      disposed = true;
      form.removeEventListener("submit", onSubmit);
      root.replaceChildren();
    },
  };
}

export default {
  apiVersion: 1,
  module: "run-postmortem.v1",
  icon: "file-text",
  surfaces: [
    {
      id: "postmortem",
      slot: "page",
      title: "Run postmortem",
      navigation: {
        label: "Run postmortem",
        labelZh: "运行复盘",
        icon: "file-text",
      },
      mount,
    },
  ],
};
