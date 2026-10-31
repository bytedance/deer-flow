import { TrajectoryCache } from "./trajectory-cache.mjs";
import { zh, PLACEHOLDER, node, label, dot, row, fold, text } from "./common.mjs";

const PAGE_SIZE = 8;

// The operator-granted mutation operations (config.yaml
// host_access.skill_mutations.operations) surface one button per skill row,
// in canonical pipeline order. Each button binds to the matching backend
// action: stage -> managed_stage, check -> managed_check,
// commit -> managed_publish, revert -> managed_rollback.
const OP_ORDER = ["stage", "check", "commit", "revert"];

function opLabel(context, op) {
  if (op === "stage") return text(context, "Stage", "暂存");
  if (op === "check") return text(context, "Check", "检查");
  if (op === "commit") return text(context, "Commit", "提交");
  return text(context, "Revert", "回滚");
}

function gatewayUrl(context, pathname) {
  const url = new URL(import.meta.url);
  const marker = url.pathname.lastIndexOf("/api/plugins/");
  if (marker < 0) {
    throw new Error(text(context, "The skill list requires packaged browser assets.", "技能列表需要通过插件资源服务加载。"));
  }
  url.pathname = url.pathname.slice(0, marker) + pathname;
  url.search = "";
  url.hash = "";
  return url;
}

async function fetchSkills(context, signal) {
  const response = await fetch(gatewayUrl(context, "/api/skills"), {
    credentials: "include",
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return data && Array.isArray(data.skills) ? data.skills : [];
}

// The caller's configured models — same public Gateway listing the chat UI
// uses, so the evolution-model picker offers exactly what the operator
// configured in config.yaml.
async function fetchModels(context, signal) {
  const response = await fetch(gatewayUrl(context, "/api/models"), {
    credentials: "include",
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return data && Array.isArray(data.models) ? data.models : [];
}

async function fetchEvolved(context) {
  const data = await context.callBackend("evolved_skills", {});
  if (!data || data.ok !== true || !Array.isArray(data.skills)) {
    const code = data && data.error && data.error.code ? data.error.code : "INTERNAL";
    throw new Error(code);
  }
  return data.skills;
}

async function callAction(context, action, payload) {
  const data = await context.callBackend(action, payload);
  if (!data || data.ok !== true) {
    const code = data && data.error && data.error.code ? data.error.code : "INTERNAL";
    throw new Error(code);
  }
  return data;
}

// Reuse the guarded host actions; automatic checking never publishes a draft.
export async function stageAndCheck(context, payload, onStaged) {
  const data = await callAction(context, "managed_stage", payload);
  const proposal = data.proposal;
  if (!proposal || typeof proposal.proposal_id !== "string" || !proposal.proposal_id) throw new Error("INVALID_PROPOSAL");
  if (context.signal?.aborted) throw new Error("ABORTED");
  onStaged(proposal);
  return callAction(context, "managed_check", { proposal_id: proposal.proposal_id });
}

export function orderTargetSkills(catalog, targets, checked = new Map()) {
  const chosen = new Set(targets);
  const selected = (name) => checked.has(name) ? checked.get(name) : chosen.has(name);
  return [...new Set([...catalog, ...targets])].sort((a, b) => Number(selected(b)) - Number(selected(a)) || a.localeCompare(b));
}

export function createTrajectoryRunContext(context, trajectory, events) {
  const t = (en, cn) => zh(context) ? cn : en;
  const box = node("div", "", { className: "skill-traj-run-context" });
  const top = node("div", "", { className: "skill-traj-context-heading" });
  top.append(node("strong", t("This run", "本次运行")));
  if (typeof trajectory.thread_id === "string" && trajectory.thread_id) {
    top.append(node("a", t("View earlier conversation", "查看前序对话"), {
      href: `/workspace/chats/${encodeURIComponent(trajectory.thread_id)}`,
      target: "_blank",
      rel: "noopener noreferrer",
      className: "skill-traj-conversation-link",
      title: t("Open the full conversation to see messages before this run", "打开完整对话，查看本轮之前的消息"),
    }));
  }
  box.append(top);
  const input = events.find((event) => event.kind === "human" && typeof event.preview === "string" && event.preview.trim());
  box.append(node("p", t("User input for this run", "本轮用户输入"), { className: "skill-traj-input-label" }));
  box.append(node("p", input?.preview || t("No user input preview is available for this run.", "本次运行暂无可展示的用户输入。"), { className: "skill-traj-input-preview" }));
  if (input) box.append(node("span", `${t("Source event", "来源事件")} #${input.seq ?? PLACEHOLDER}`, { className: "skill-traj-run-meta" }));
  box.append(node("p", t("Events follow their recorded order; activation may be recorded before the user input. Earlier messages are in the full conversation.", "事件按记录顺序展示，激活记录可能早于本轮输入；更早的消息可在完整对话中查看。"), { className: "skill-traj-hint" }));
  return box;
}

export function trajectoryActivationPoints(events) {
  return (Array.isArray(events) ? events : []).flatMap((event, index) =>
    event?.invocation === true ? [{ index, eventId: event.event_id, seq: event.seq }] : [],
  );
}

export function evolutionModelChoices(models) {
  return (Array.isArray(models) ? models : [])
    .filter((model) => model && typeof model.name === "string" && model.name)
    .map((model) => ({ name: model.name, display: model.display_name || model.name }));
}

function methodLabel(context, method) {
  if (method === "revert") return text(context, "Reverted", "已回滚");
  return text(context, "Saved", "已保存");
}

// Trajectory timeline readability: each event renders with a kind label and,
// where the sealed journal carries it, a bounded preview of the caller's own
// content (their message, the model's reply, or the tool name + excerpt).
function eventKindLabel(context, kind) {
  if (kind === "human") return text(context, "You", "用户");
  if (kind === "ai") return text(context, "Model", "模型");
  if (kind === "tool") return text(context, "Tool", "工具");
  return text(context, "Skill", "技能");
}

// Plan B (feedback_mode: agent): bounded LCS line diff between the current
// SKILL.md and the model's draft. Returns null when either side is too large
// to diff in the page; the caller degrades to a notice.
const DIFF_LINE_CAP = 1000;

function lineDiff(before, after) {
  const a = String(before || "").split("\n");
  const b = String(after || "").split("\n");
  if (a.length > DIFF_LINE_CAP || b.length > DIFF_LINE_CAP) return null;
  const n = a.length;
  const m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const rows = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: "del", text: a[i] });
      i += 1;
    } else {
      rows.push({ type: "add", text: b[j] });
      j += 1;
    }
  }
  while (i < n) rows.push({ type: "del", text: a[i++] });
  while (j < m) rows.push({ type: "add", text: b[j++] });
  return rows;
}

function diffView(context, base, result) {
  const t = (en, cn) => text(context, en, cn);
  const box = node("div", "", { className: "skill-evo-diff" });
  const rows = lineDiff(base, result);
  if (!rows) {
    box.append(node("p", t("Diff too large to display in the page.", "差异过大，无法在页面中展示。"), { className: "skill-evo-diff-empty" }));
    return box;
  }
  let add = 0;
  let del = 0;
  rows.forEach((row) => {
    if (row.type === "add") add += 1;
    if (row.type === "del") del += 1;
  });
  box.append(node("p", t(`+${add} / -${del} lines`, `新增 ${add} 行 / 删除 ${del} 行`), { className: "skill-evo-diff-summary" }));
  const list = node("div", "", { className: "skill-evo-diff-rows" });
  rows.forEach((row) => {
    const marker = row.type === "add" ? "+ " : row.type === "del" ? "- " : "  ";
    list.append(
      node("div", marker + row.text, {
        className: `skill-evo-diff-row skill-evo-diff-${row.type}`,
      }),
    );
  });
  box.append(list);
  return box;
}

// Host page h1 → evolution module h2 → section h3 → configuration group h4.
function createSectionHeading(title, description) {
  const header = node("header", "", { className: "status-header" });
  header.append(
    node("h3", title, { className: "status-title" }),
    node("p", description, { className: "status-intro" }),
  );
  return header;
}

export function createSkillsCard(context) {
  const t = (en, cn) => text(context, en, cn);
  const card = node("section", "", { className: "status-card skill-card-primary" });
  card.append(createSectionHeading(
    t("Self-evolved skills", "自演进技能"),
    t("Review evolved skills, annotate usage trajectories and manage versions.", "查看已演进的技能，标注使用轨迹并管理版本变更。"),
  ));
  const body = node("div", "", { className: "skill-list" });
  const pager = node("div", "", { className: "skill-pager", hidden: true });
  const prev = node("button", t("Previous", "上一页"), {
    type: "button",
    className: "skill-page-btn",
  });
  const next = node("button", t("Next", "下一页"), {
    type: "button",
    className: "skill-page-btn",
  });
  const indicator = node("span", "", { className: "skill-page-indicator" });
  let skills = [];
  let page = 0;
  let operations = [];
  // Per-skill page state: the staged-but-uncommitted proposal and the last
  // operation outcome shown under the row.
  const pending = new Map();
  const inFlight = new Set();
  const notes = new Map();
  let editorFor = null;
  let versionFor = null;
  let versionMode = "view";
  // "View changes" state: operation_id -> { before, after } fetched from the
  // version journal, rendered inline under that history entry.
  const versionDiffs = new Map();
  // Trajectory state: which skill's panel is open, its loaded data, and the
  // event whose annotation editor is open (identified by run_id + event_id).
  // Evolution mode from the status snapshot / config card: "draft" (append)
  // offers the deterministic annotation draft button; "agent" (model)
  // delegates to the agent-side skill_feedback tool and
  // annotation-triggered evolution jobs. The page-level switch
  // (evolution_mode) maps onto these two shapes.
  let feedbackMode = "draft";
  let trajFor = null;
  const expandedRuns = new Set();
  const locatedActivations = new Map();
  const trajs = new TrajectoryCache({
    load: (name) => callAction(context, "skill_trajectories", { skill_name: name }),
    signal: context.signal,
    onChange: (name) => {
      // Background completions must not reset an annotation being edited.
      if (trajFor === name && !annotFor) paint();
    },
  });
  let annotFor = null;
  // Evolution job state (agent mode): the latest job per skill, plus one
  // poll timer scoped to the open trajectory panel.
  const evoJobs = new Map();
  let evoTimer = null;

  function stopEvoPoll() {
    if (evoTimer !== null) {
      clearInterval(evoTimer);
      evoTimer = null;
    }
  }

  function setOperations(ops) {
    operations = Array.isArray(ops) ? OP_ORDER.filter((op) => ops.includes(op)) : [];
    paint();
  }

  function setFeedbackMode(mode) {
    feedbackMode = mode === "agent" ? "agent" : "draft";
    paint();
  }

  function note(name, message, tone) {
    if (message == null) notes.delete(name);
    else notes.set(name, { message, tone });
  }

  function failText(error) {
    if (error?.message === "CHAT_MODELS_UNAVAILABLE") return t("Chat model access is unavailable; update and restart the Gateway.", "当前宿主未提供对话模型调用能力，请更新并重启 Gateway。");
    return `${t("Operation failed", "操作失败")}: ${error && error.message ? error.message : "INTERNAL"}`;
  }

  function pageCount() {
    return Math.max(1, Math.ceil(skills.length / PAGE_SIZE));
  }

  function editor(name) {
    const box = node("div", "", { className: "skill-editor" });
    const area = node("textarea", "", {
      className: "skill-editor-area",
      rows: 12,
      placeholder: t("Loading the current SKILL.md…", "正在读取当前 SKILL.md…"),
    });
    const actions = node("div", "", { className: "skill-editor-actions" });
    const cancel = node("button", t("Cancel", "取消"), { type: "button", className: "skill-op-btn" });
    const confirm = node("button", t("Stage proposal", "暂存提案"), {
      type: "button",
      className: "skill-op-btn skill-op-primary",
      disabled: inFlight.has(name),
    });
    cancel.onclick = () => {
      editorFor = null;
      paint();
    };
    confirm.onclick = () => void submitStage(name, area.value);
    area.addEventListener("input", () => {
      area.dataset.dirty = "1";
    });
    actions.append(cancel, confirm);
    box.append(area, actions);
    return box;
  }

  async function loadEditorContent(name) {
    try {
      const data = await callAction(context, "managed_read", { skill_name: name });
      const area = body.querySelector(".skill-editor-area");
      if (editorFor === name && area && !area.dataset.dirty) {
        const content = data.skill && data.skill.content;
        if (typeof content === "string") area.value = content;
      }
    } catch (error) {
      if (context.signal?.aborted) return;
      const area = body.querySelector(".skill-editor-area");
      if (area && !area.dataset.dirty) area.placeholder = t("Could not load the current content; edit from scratch.", "无法读取当前内容，请直接编辑。");
    }
  }

  function showCheckResult(name, state, data) {
    state.decision = data.check && data.check.decision ? data.check.decision : PLACEHOLDER;
    state.reason_code = data.check && data.check.reason_code ? data.check.reason_code : null;
    const decision = state.decision === "allow" ? t("Passed", "通过") : state.decision === "deny" ? t("Rejected", "拒绝") : state.decision;
    const reason = state.reason_code ? ` · ${state.reason_code}` : "";
    note(name, `${t("Check finished", "检查完成")}: ${decision}${reason}`, state.decision === "allow" ? "ok" : "err");
  }

  async function submitStage(name, content) {
    if (inFlight.has(name)) return;
    if (!content || !content.trim()) {
      note(name, t("Content is required.", "内容不能为空。"), "err");
      paint();
      return;
    }
    inFlight.add(name);
    let state;
    try {
      const result = await stageAndCheck(context, { skill_name: name, content }, (proposal) => {
        state = { proposal_id: proposal.proposal_id, decision: null, reason_code: null };
        pending.set(name, state);
        editorFor = null;
        note(name, t("Staged. Checking automatically…", "已暂存，正在自动检查…"), "ok");
        paint();
      });
      if (context.signal?.aborted) return;
      showCheckResult(name, state, result);
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, state
        ? `${t("Staged, but automatic check failed; use Check to retry", "已暂存，但自动检查失败，可点击检查重试")}: ${failText(error)}`
        : failText(error), "err");
    } finally {
      inFlight.delete(name);
    }
    paint();
  }

  async function runPipeline(op, name, operationId) {
    if (inFlight.has(name)) return;
    inFlight.add(name);
    try {
      if (op === "check") {
        const state = pending.get(name);
        if (!state) return;
        state.decision = null;
        state.reason_code = null;
        note(name, t("Checking…", "正在检查…"), "ok");
        paint();
        const data = await callAction(context, "managed_check", { proposal_id: state.proposal_id });
        showCheckResult(name, state, data);
      } else if (op === "commit") {
        const state = pending.get(name);
        if (!state) return;
        await callAction(context, "managed_publish", { proposal_id: state.proposal_id });
        pending.delete(name);
        note(name, t("Committed.", "已提交。"), "ok");
      } else if (op === "revert") {
        await callAction(context, "managed_rollback", { operation_id: operationId });
        note(name, t("Reverted.", "已回滚。"), "ok");
      }
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, failText(error), "err");
    } finally {
      inFlight.delete(name);
    }
    paint();
    if (op === "commit" || op === "revert") await refresh();
  }

  // The host's revert only undoes the current head operation, so restoring an
  // older version replays its saved bytes through the normal stage → check →
  // commit pipeline as a new forward version.
  async function restoreVersion(name, entry) {
    try {
      const data = await callAction(context, "evolved_version", { operation_id: entry.operation_id });
      const content = data.version && data.version.content;
      if (typeof content !== "string") throw new Error("NOT_FOUND_OR_FORBIDDEN");
      versionFor = null;
      editorFor = name;
      note(name, t("Version loaded; review it, then stage.", "已载入该版本内容，确认后暂存。"), "ok");
      paint();
      const area = body.querySelector(".skill-editor-area");
      if (area) {
        area.value = content;
        area.dataset.dirty = "1";
      }
      return;
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, failText(error), "err");
    }
    paint();
  }

  // "View changes" for one history entry: fetch this version's saved content
  // and the one before it (history is newest-first, so the previous version is
  // the next array entry), then render the line diff inline under the entry.
  // The earliest retained version diffs against empty content.
  async function viewChanges(entry, prevEntry) {
    try {
      const [current, previous] = await Promise.all([
        callAction(context, "evolved_version", { operation_id: entry.operation_id }),
        prevEntry && prevEntry.has_content
          ? callAction(context, "evolved_version", { operation_id: prevEntry.operation_id })
          : Promise.resolve(null),
      ]);
      const after = current.version && typeof current.version.content === "string" ? current.version.content : "";
      const before = previous && previous.version && typeof previous.version.content === "string" ? previous.version.content : "";
      versionDiffs.set(entry.operation_id, { before, after });
    } catch (error) {
      if (context.signal?.aborted) return;
      versionDiffs.delete(entry.operation_id);
      versionDiffs.set(entry.operation_id, { error: error && error.message ? error.message : "INTERNAL" });
    }
    paint();
  }

  function versionPanel(skill) {
    const readOnly = versionMode === "view";
    const panel = node("div", "", { className: "skill-versions" });
    panel.append(
      node("p", readOnly
        ? t("Version history — review saved versions and their changes.", "版本历史——查看已保存的版本及每次变更。")
        : t("Version history — undo the latest operation, or restore an older version as a new one.", "版本历史——可撤销最新操作，或将旧版本内容恢复为新版本。"), {
        className: "skill-versions-hint",
      }),
    );
    const entries = Array.isArray(skill.history) ? skill.history : [];
    if (!entries.length) {
      panel.append(node("p", t("No recorded versions yet.", "暂无版本记录。"), { className: "skill-versions-empty" }));
      return panel;
    }
    entries.forEach((entry, index) => {
      const item = node("div", "", { className: index === 0 ? "skill-version skill-version-head" : "skill-version" });
      const label = node(
        "span",
        `v${entry.seq == null ? PLACEHOLDER : entry.seq} · ${entry.method === "revert" ? t("revert", "回滚") : t("commit", "提交")} · ${entry.updated_at || PLACEHOLDER}`,
        { className: "skill-version-label" },
      );
      const ops = node("div", "", { className: "skill-version-ops" });
      const changes = node(
        "button",
        versionDiffs.has(entry.operation_id) ? t("Hide changes", "隐藏变更") : t("View changes", "查看变更"),
        { type: "button", className: "skill-op-btn" },
      );
      if (!entry.has_content) {
        changes.disabled = true;
        changes.title = t("No content snapshot for this version.", "该版本无内容快照。");
      } else {
        changes.onclick = () => {
          if (versionDiffs.has(entry.operation_id)) {
            versionDiffs.delete(entry.operation_id);
            paint();
            return;
          }
          void viewChanges(entry, entries[index + 1]);
        };
      }
      ops.append(changes);
      if (!readOnly && index === 0) {
        const undo = node("button", t("Undo this operation", "撤销此操作"), { type: "button", className: "skill-op-btn" });
        undo.onclick = () => {
          versionFor = null;
          void runPipeline("revert", skill.name, entry.operation_id);
        };
        const cancel = node("button", t("Cancel", "取消"), { type: "button", className: "skill-op-btn" });
        cancel.onclick = () => {
          versionFor = null;
          paint();
        };
        ops.append(undo, cancel);
      } else if (!readOnly) {
        const restore = node("button", t("Restore this version", "恢复此版本"), { type: "button", className: "skill-op-btn" });
        if (!entry.has_content) {
          restore.disabled = true;
          restore.title = t("No content snapshot for this version.", "该版本无内容快照。");
        }
        restore.onclick = () => void restoreVersion(skill.name, entry);
        ops.append(restore);
      }
      item.append(label, ops);
      const diff = versionDiffs.get(entry.operation_id);
      if (diff) {
        if (diff.error) {
          item.append(node("p", `${t("Could not load the version contents", "版本内容加载失败")}: ${diff.error}`, { className: "skill-version-diff-error" }));
        } else {
          if (!entries[index + 1]) {
            item.append(
              node("p", t("Earliest retained version — diffed against empty content.", "最早保留版本——与空内容对比。"), {
                className: "skill-version-diff-note",
              }),
            );
          }
          item.append(diffView(context, diff.before, diff.after));
        }
      }
      panel.append(item);
    });
    return panel;
  }

  // Trajectories: the most recent sealed runs that activated this skill, with
  // the activation events (调用点) highlighted. Clicking an event opens an
  // annotation editor backed by the plugin-owned skill_annotations store.
  function loadTrajectories(name, { force = false } = {}) {
    const request = trajs.load(name, { force, priority: true });
    paint();
    return request;
  }

  function warmTrajectories() {
    // Prioritize this page, then the next page; do not scan every skill.
    trajs.warm(skills.slice(page * PAGE_SIZE, (page + 2) * PAGE_SIZE).map((skill) => skill.name));
  }

  async function saveAnnotation(name, runId, eventId, noteText) {
    try {
      await callAction(context, "trajectory_annotate", {
        skill_name: name,
        run_id: runId,
        event_id: eventId,
        note: noteText,
      });
      annotFor = null;
      note(name, t("Annotation saved.", "标注已保存。"), "ok");
      // A saved annotation supersedes a consumed draft: the backend
      // auto-clears the published job, so refresh the evolution panel back
      // to the trigger state.
      if (feedbackMode === "agent") void refreshEvolution(name);
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, failText(error), "err");
    }
    await loadTrajectories(name, { force: true });
  }

  async function removeAnnotation(name, runId, eventId) {
    try {
      await callAction(context, "trajectory_unannotate", {
        skill_name: name,
        run_id: runId,
        event_id: eventId,
      });
      annotFor = null;
      note(name, t("Annotation removed.", "标注已删除。"), "ok");
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, failText(error), "err");
    }
    await loadTrajectories(name, { force: true });
  }

  function annotationEditor(name, traj, event, existing) {
    const box = node("div", "", { className: "skill-annot" });
    const area = node("textarea", "", {
      className: "skill-annot-area",
      rows: 3,
      placeholder: t("Annotate this event…", "为该事件添加标注…"),
    });
    if (existing) area.value = existing;
    const actions = node("div", "", { className: "skill-editor-actions" });
    const cancel = node("button", t("Cancel", "取消"), { type: "button", className: "skill-op-btn" });
    const remove = node("button", t("Remove", "删除"), { type: "button", className: "skill-op-btn" });
    const save = node("button", t("Save", "保存"), { type: "button", className: "skill-op-btn skill-op-primary" });
    cancel.onclick = () => {
      annotFor = null;
      paint();
    };
    remove.disabled = !existing;
    remove.onclick = () => void removeAnnotation(name, traj.run_id, event.event_id);
    save.onclick = () => {
      const value = area.value;
      if (!value || !value.trim()) {
        area.placeholder = t("The annotation cannot be empty.", "标注内容不能为空。");
        return;
      }
      void saveAnnotation(name, traj.run_id, event.event_id, value);
    };
    actions.append(cancel, remove, save);
    box.append(area, actions);
    return box;
  }

  function trajectoryPanel(name) {
    const state = trajs.get(name) || { loading: false, data: null, error: null };
    const panel = node("div", "", { className: "skill-traj" });
    panel.append(
      node(
        "p",
        t(
          "Recent trajectories — click a run to expand its events. Click an event to annotate it.",
          "最近使用轨迹——点击运行记录展开事件详情，点击事件可添加标注。",
        ),
        { className: "skill-traj-hint" },
      ),
    );
    if (state.loading && !state.data) {
      panel.append(node("p", t("Loading trajectories…", "正在加载轨迹…"), { className: "skill-traj-empty" }));
      if (feedbackMode === "agent") panel.append(evolutionPanel(name));
      return panel;
    }
    if (state.error && !state.data) {
      const message =
        state.error === "UNAVAILABLE"
          ? t("Trajectories are unavailable: the sealed evidence reader is not granted.", "轨迹不可用：未授权封存运行证据读取器。")
          : `${t("Could not load the trajectories", "轨迹加载失败")}: ${state.error}`;
      panel.append(node("p", message, { className: "skill-traj-empty" }));
      if (feedbackMode === "agent") panel.append(evolutionPanel(name));
      return panel;
    }
    if (state.loading || state.error) {
      panel.append(node("p", state.error
        ? t("Could not refresh; showing cached trajectories. Use Refresh to retry.", "暂时无法更新，正在展示已缓存轨迹；可点击刷新重试。")
        : t("Showing cached trajectories while updating…", "已展示缓存轨迹，正在后台更新…"), { className: "skill-traj-hint" }));
    }
    const trajectories = (state.data && Array.isArray(state.data.trajectories) ? state.data.trajectories : []).slice(0, 3);
    if (!trajectories.length) {
      panel.append(
        node("p", t("No recorded runs used this skill yet.", "暂无使用过该技能的运行记录。"), { className: "skill-traj-empty" }),
      );
      if (feedbackMode === "agent") panel.append(evolutionPanel(name));
      return panel;
    }
    trajectories.forEach((traj) => {
      const annotations = new Map(
        (Array.isArray(traj.annotations) ? traj.annotations : []).map((a) => [String(a.event_id), a]),
      );
      const events = Array.isArray(traj.events) ? traj.events : [];
      const points = trajectoryActivationPoints(events);
      const block = node("details", "", { className: "skill-traj-run" });
      const runId = traj.run_id == null ? "" : String(traj.run_id);
      const runKey = JSON.stringify([name, runId]);
      block.open = expandedRuns.has(runKey);
      block.ontoggle = () => {
        if (!block.isConnected) return;
        if (block.open) expandedRuns.add(runKey);
        else expandedRuns.delete(runKey);
      };
      const head = node("summary", "", { className: "skill-traj-run-head" });
      head.append(
        node("span", `${t("Run", "本次运行")} ${runId.slice(0, 8)} · ${traj.status || PLACEHOLDER}`, {
          className: "skill-traj-run-id",
        }),
        node(
          "span",
          `${traj.created_at || PLACEHOLDER} · ${t("events", "事件")}: ${traj.event_count == null ? PLACEHOLDER : traj.event_count}`,
          { className: "skill-traj-run-meta" },
        ),
      );
      const activationLabel = points.map((point) => `#${point.seq ?? PLACEHOLDER}`).join("、");
      if (points.length) {
        head.append(node("span", `${t("Activation points", "激活点")}: ${activationLabel}`, { className: "skill-traj-activation-list" }));
      }
      block.append(head, createTrajectoryRunContext(context, traj, events));
      if (traj.timeline_truncated) {
        block.append(node("p", t("Showing up to 200 visible events around the first recorded skill activation. Open the full conversation for more context.", "当前展示首个技能激活点附近最多 200 条可见事件；更多上下文请查看完整对话。"), { className: "skill-traj-hint skill-traj-context-hint" }));
      }
      const timeline = node("div", "", { className: "skill-traj-timeline" });
      const eventLines = [];
      events.forEach((event) => {
        const line = node("button", "", { type: "button", className: "skill-traj-event" });
        if (event.invocation) line.classList.add("skill-traj-invocation");
        line.append(
          node("span", `#${event.seq == null ? PLACEHOLDER : event.seq}`, {
            className: "skill-traj-seq",
          }),
          node("span", eventKindLabel(context, event.kind), {
            className: `skill-traj-kind skill-traj-kind-${event.kind || "system"}`,
          }),
        );
        if (event.invocation) {
          const detail = event.detail || {};
          line.append(
            node("span", t("Invocation", "调用点"), { className: "skill-traj-badge" }),
            node("span", detail.path ? `path: ${detail.path}` : "", { className: "skill-traj-event-meta" }),
          );
        }
        if (event.label) {
          line.append(node("span", event.label, { className: "skill-traj-tool" }));
        }
        if (event.preview) {
          line.append(node("span", event.preview, { className: "skill-traj-preview" }));
        }
        line.title = t("Click to annotate", "点击添加标注");
        line.onclick = () => {
          annotFor = annotFor && annotFor.runId === traj.run_id && annotFor.eventId === event.event_id ? null : { runId: traj.run_id, eventId: event.event_id };
          paint();
        };
        eventLines.push(line);
        timeline.append(line);
        const existing = annotations.get(String(event.event_id));
        if (existing) {
          timeline.append(
            node("p", `${t("Note", "标注")}: ${existing.note}`, { className: "skill-traj-note" }),
          );
        }
        if (
          annotFor &&
          annotFor.runId === traj.run_id &&
          String(annotFor.eventId) === String(event.event_id)
        ) {
          timeline.append(annotationEditor(name, traj, event, existing ? existing.note : null));
        }
      });
      const highlight = (index) => {
        eventLines.forEach((line, i) => {
          line.classList.toggle("skill-traj-located", i === index);
          line.classList.toggle("skill-traj-context", index >= 0 && Math.abs(i - index) === 1);
          if (i === index) line.setAttribute("aria-current", "step");
          else line.removeAttribute("aria-current");
        });
      };
      let selected = points.findIndex((point) => point.eventId === locatedActivations.get(runKey));
      highlight(selected >= 0 ? points[selected].index : -1);
      if (points.length) {
        const locate = node("button", `${t("Locate activation", "定位激活点")}${selected >= 0 ? ` ${selected + 1}/${points.length}` : ""}`, { type: "button", className: "skill-op-btn skill-traj-locate" });
        locate.title = t("Expand and locate each recorded activation in turn", "展开记录并依次定位每一个已记录的激活点");
        locate.onclick = (event) => {
          event.preventDefault();
          event.stopPropagation();
          selected = (selected + 1) % points.length;
          const point = points[selected];
          locatedActivations.set(runKey, point.eventId);
          expandedRuns.add(runKey);
          block.open = true;
          highlight(point.index);
          locate.textContent = `${t("Locate activation", "定位激活点")} ${selected + 1}/${points.length}`;
          const target = eventLines[point.index];
          target.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
          target.focus({ preventScroll: true });
        };
        head.append(locate);
        block.append(node("p", t("Highlighted neighbors provide context; they are not proof of skill execution.", "高亮的前后事件仅供查看上下文，不代表这些步骤均由该技能执行。"), { className: "skill-traj-hint skill-traj-context-hint" }));
      }
      block.append(timeline);
      panel.append(block);
    });
    if (feedbackMode === "agent") panel.append(evolutionPanel(name));
    return panel;
  }

  // Plan A (feedback_mode: draft): the backend synthesizes the current
  // SKILL.md plus a usage-feedback section from the caller's annotations;
  // the draft lands in the normal stage editor so the guarded pipeline
  // (stage → check → commit) applies unchanged.
  async function loadDraft(name) {
    try {
      const data = await callAction(context, "annotation_draft", { skill_name: name });
      const content = typeof data.content === "string" ? data.content : "";
      const included = typeof data.included_count === "number" ? data.included_count : 0;
      editorFor = name;
      versionFor = null;
      trajFor = null;
      annotFor = null;
      note(
        name,
        included
          ? t(`Draft built from ${included} annotation(s); review it, then stage.`, `已基于 ${included} 条标注生成草案，确认后暂存。`)
          : data.already_included_count > 0
            ? t("All annotations are already included; the draft equals the current content.", "标注已包含在当前技能中，无需重复追加。")
            : t("No annotations yet; the draft equals the current content.", "暂无标注，草案与当前内容一致。"),
        "ok",
      );
      paint();
      const area = body.querySelector(".skill-editor-area");
      if (area) {
        area.value = content;
        area.dataset.dirty = "1";
      }
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, failText(error), "err");
      paint();
    }
  }

  // Plan B (feedback_mode: agent): confirming annotations can trigger a
  // plugin-driven model evolution job. The launch action returns immediately
  // with a job id; the page polls evolution_status while the job runs, then
  // renders a line diff of the model's draft against the current content.
  // Publishing stays human-gated: "Stage this draft" replays the draft into
  // the normal stage → check → commit editor.
  // Model choice is per-launch, never persisted: the picker lists the
  // caller's ordinary chat models (/api/models), selected by model_name.
  let evolutionModels = [];
  let evolutionDefaultModel = null;
  const evoModelChoice = new Map();

  async function loadEvolutionModels() {
    try {
      const modelData = await fetchModels(context, context.signal);
      evolutionModels = evolutionModelChoices(modelData);
      evolutionDefaultModel = evolutionModels[0]?.name || null;
    } catch (error) {
      evolutionModels = [];
      evolutionDefaultModel = null;
    }
    if (context.signal?.aborted) return;
    if (trajFor) paint();
  }

  async function refreshEvolution(name) {
    try {
      const data = await callAction(context, "evolution_status", { skill_name: name });
      const job = data && data.job ? data.job : null;
      const previous = evoJobs.get(name) || null;
      evoJobs.set(name, job);
      if (previous && previous.status === "running" && job && job.status !== "running" && trajFor === name) {
        // Replace the transient "started" note with the outcome so a quiet
        // terminal panel never looks like a stuck launch.
        if (job.status === "succeeded") {
          if (job.published) note(name, t("Draft published through the pipeline.", "该草案已通过管线发布。"), "ok");
          else if (job.unchanged) note(name, t("The model kept the current content; nothing to change.", "模型保持了当前内容，无需修改。"), "ok");
          else note(name, t("Draft ready — review the diff below.", "草案已生成，请在下方查看差异。"), "ok");
        } else {
          note(name, `${t("Evolution failed", "演进失败")}: ${job.error_code || "INTERNAL"}`, "err");
        }
      }
      if (!job || job.status !== "running") {
        // Terminal (or absent): stop polling so the finished diff stops
        // repainting and its scroll position stays usable.
        stopEvoPoll();
      } else if (trajFor === name && evoTimer === null) {
        evoTimer = setInterval(() => {
          if (context.signal?.aborted || trajFor !== name) {
            stopEvoPoll();
            return;
          }
          void refreshEvolution(name);
        }, 2000);
      }
      if (trajFor === name) paint();
    } catch (error) {
      if (context.signal?.aborted) return;
      evoJobs.set(name, null);
      if (trajFor === name) paint();
    }
  }

  async function startEvolution(name) {
    try {
      // Use the same visible model catalog as chat, including its first
      // visible model as the default. No plugin-specific role list is needed.
      const choice = evoModelChoice.get(name) || "";
      const selectedModel = choice || evolutionDefaultModel;
      const payload = selectedModel ? { skill_name: name, model_name: selectedModel } : { skill_name: name };
      const data = await callAction(context, "annotation_evolve", payload);
      evoJobs.set(name, { job_id: data.job_id, skill_name: name, status: "running" });
      stopEvoPoll();
      evoTimer = setInterval(() => {
        if (context.signal?.aborted || trajFor !== name) {
          stopEvoPoll();
          return;
        }
        void refreshEvolution(name);
      }, 2000);
      note(name, t("Evolution job started…", "演进任务已启动…"), "ok");
      paint();
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, failText(error), "err");
      paint();
    }
  }

  async function discardEvolution(name, jobId) {
    try {
      await callAction(context, "evolution_discard", { skill_name: name, job_id: jobId });
      evoJobs.delete(name);
      note(name, t("Draft discarded.", "已丢弃该草案。"), "ok");
      paint();
    } catch (error) {
      if (context.signal?.aborted) return;
      note(name, failText(error), "err");
      paint();
    }
  }

  function evolutionPanel(name) {
    const box = node("div", "", { className: "skill-evo" });
    const trigger = node("button", t("Evolve from feedback", "确认并优化"), {
      type: "button",
      className: "skill-op-btn skill-evo-btn",
    });
    trigger.title = t("Run a model evolution job over the current content plus your annotations", "基于当前内容与你的标注触发一次模型演进");
    trigger.onclick = () => void startEvolution(name);
    const job = evoJobs.get(name) || null;
    if (!job) {
      box.append(
        node("p", t("Confirm your annotations, then trigger a model evolution of this skill.", "确认标注后，可触发一次该技能的模型演进。"), {
          className: "skill-evo-hint",
        }),
      );
      // Model choice: one of the caller's configured models. Always shown
      // once the chat catalog loads — even a single-model host sees it.
      // User model permissions are enforced by the host on every invocation.
      if (evolutionModels.length) {
        const picker = node("label", "", { className: "skill-evo-model" });
        picker.append(node("span", t("Model", "模型"), { className: "skill-evo-model-label" }));
        const select = node("select", "", { className: "skill-evo-model-select" });
        const defaultOption = node("option", `${t("Default", "默认")}${evolutionDefaultModel ? ` (${evolutionDefaultModel})` : ""}`, { value: "" });
        if (!(evoModelChoice.get(name) || "")) defaultOption.selected = true;
        select.append(defaultOption);
        for (const model of evolutionModels) {
          if (model.name === evolutionDefaultModel) continue;
          const option = node("option", model.display, { value: model.name });
          if (evoModelChoice.get(name) === model.name) option.selected = true;
          select.append(option);
        }
        select.onchange = () => evoModelChoice.set(name, select.value);
        picker.append(select);
        box.append(picker);
        box.append(
          node(
            "p",
            evolutionModels.length > 1
              ? t("Uses the same models and user permissions as chat. No plugin-specific model configuration or authorization is required.", "沿用对话中的模型列表与用户权限，无需为插件单独配置或授权。")
              : t("Only one chat model is available; it is used automatically.", "当前只有一个可用的对话模型，将自动使用该模型。"),
            { className: "skill-evo-model-note" },
          ),
        );
      }
      box.append(trigger);
      return box;
    }
    if (job.status === "running") {
      box.append(
        node("p", `${t("Evolving… polling for progress", "演进中……正在轮询进度")} (${job.job_id || PLACEHOLDER})`, {
          className: "skill-evo-running",
        }),
      );
      return box;
    }
    if (job.status === "succeeded") {
      if (job.published) {
        // The draft already went through the managed pipeline: show a quiet
        // confirmation instead of resurrecting the diff on every visit.
        box.append(
          node("p", t("This draft was published through the pipeline.", "该草案已通过管线发布。"), {
            className: "skill-evo-published",
          }),
        );
        const clear = node("button", t("Clear record", "清除记录"), { type: "button", className: "skill-op-btn" });
        clear.onclick = () => void discardEvolution(name, job.job_id);
        const clearActions = node("div", "", { className: "skill-evo-actions" });
        clearActions.append(clear);
        box.append(clearActions);
        return box;
      }
      if (job.unchanged) {
        // The model reviewed the annotations and kept the content as is:
        // say so plainly instead of an empty diff.
        box.append(
          node("p", t("The model kept the current content — your annotations are already covered.", "模型保持了当前内容——标注已被现有内容覆盖，无变更。"), {
            className: "skill-evo-published",
          }),
        );
        const clear = node("button", t("Clear record", "清除记录"), { type: "button", className: "skill-op-btn" });
        clear.onclick = () => void discardEvolution(name, job.job_id);
        const clearActions = node("div", "", { className: "skill-evo-actions" });
        clearActions.append(clear);
        box.append(clearActions);
        return box;
      }
      const meta = node("p", "", { className: "skill-evo-meta" });
      meta.append(
        node(
          "span",
          `${t("Draft ready", "草案已生成")}: ${job.resolved_model || PLACEHOLDER}` +
            (job.input_tokens != null || job.output_tokens != null ? ` · ${t("tokens", "令牌")}: ${(job.input_tokens || 0) + (job.output_tokens || 0)}` : ""),
        ),
      );
      const stage = node("button", t("Stage this draft", "暂存此草案"), {
        type: "button",
        className: "skill-op-btn skill-op-primary",
      });
      stage.onclick = () => {
        stopEvoPoll();
        editorFor = name;
        versionFor = null;
        trajFor = null;
        annotFor = null;
        note(name, t("Model draft loaded; review it, then stage.", "已载入模型草案，确认后暂存。"), "ok");
        paint();
        const area = body.querySelector(".skill-editor-area");
        if (area) {
          area.value = typeof job.result_content === "string" ? job.result_content : "";
          area.dataset.dirty = "1";
        }
      };
      const discard = node("button", t("Discard", "丢弃"), { type: "button", className: "skill-op-btn" });
      discard.onclick = () => void discardEvolution(name, job.job_id);
      const actions = node("div", "", { className: "skill-evo-actions" });
      actions.append(stage, discard);
      box.append(meta, diffView(context, job.base_content, job.result_content), actions);
      return box;
    }
    // failed
    box.append(
      node("p", `${t("Evolution failed", "演进失败")}: ${job.error_code || PLACEHOLDER}`, {
        className: "skill-evo-failed",
      }),
      trigger,
    );
    return box;
  }

  function opsButtons(skill) {
    const name = skill.name == null ? "" : String(skill.name);
    const group = node("div", "", { className: "skill-ops" });
    const versions = node("button", t("View versions", "查看版本"), { type: "button", className: "skill-op-btn" });
    versions.onclick = () => {
      versionFor = versionFor === name && versionMode === "view" ? null : name;
      versionMode = "view";
      editorFor = null;
      trajFor = null;
      annotFor = null;
      stopEvoPoll();
      paint();
    };
    group.append(versions);
    for (const op of operations) {
      const button = node("button", opLabel(context, op), { type: "button", className: "skill-op-btn" });
      if (op === "stage") {
        button.onclick = () => {
          editorFor = editorFor === name ? null : name;
          if (editorFor === name) versionFor = null;
          if (editorFor === name) trajFor = null;
          paint();
          if (editorFor === name) void loadEditorContent(name);
        };
      } else if (op === "check" || op === "commit") {
        if (!pending.get(name)) button.disabled = true;
        if (op === "commit" && pending.get(name)?.decision !== "allow") button.disabled = true;
        button.onclick = () => void runPipeline(op, name);
      } else if (op === "revert") {
        button.onclick = () => {
          versionFor = versionFor === name && versionMode === "rollback" ? null : name;
          versionMode = "rollback";
          editorFor = null;
          trajFor = null;
          paint();
        };
      }
      if (inFlight.has(name)) button.disabled = true;
      group.append(button);
    }
    // Always offered (it only reads sealed evidence through the extension's
    // own backend action); the panel explains when the reader is not granted.
    const traj = node("button", t("Trajectories", "轨迹"), {
      type: "button",
      className: "skill-op-btn skill-traj-btn",
    });
    traj.onclick = () => {
      if (trajFor === name) {
        trajFor = null;
        annotFor = null;
        stopEvoPoll();
        paint();
        return;
      }
      trajFor = name;
      editorFor = null;
      versionFor = null;
      annotFor = null;
      void loadTrajectories(name);
      if (feedbackMode === "agent") {
        void refreshEvolution(name);
        void loadEvolutionModels();
      }
    };
    group.append(traj);
    // Offered only in draft feedback mode; the backend enforces the same
    // switch server-side, so the button never appears in agent mode.
    if (feedbackMode === "draft") {
      const draft = node("button", t("Draft from feedback", "标注草案"), {
        type: "button",
        className: "skill-op-btn skill-draft-btn",
      });
      draft.title = t("Build a draft from the current content plus your annotations", "基于当前内容与你的标注生成草案");
      draft.onclick = () => void loadDraft(name);
      group.append(draft);
    }
    return group;
  }

  function evolvedRow(skill, catalog) {
    const name = skill.name == null ? "" : String(skill.name);
    const live = catalog.get(name);
    const reverted = skill.method === "revert";
    const item = node("div", "", { className: "skill-row" });
    const head = node("div", "", { className: "skill-row-head" });
    const meta = node("span", "", { className: "status-value" });
    meta.append(
      node("span", methodLabel(context, skill.method), {
        className: reverted ? "skill-badge skill-badge-muted" : "skill-badge",
      }),
    );
    if (live) {
      meta.append(dot(live.enabled === false ? "muted" : "ok"), node("span", label(context, live.enabled !== false)));
    } else {
      meta.append(node("span", t("Not in catalog", "不在技能目录"), { className: "skill-missing" }));
    }
    head.append(
      node("span", name || PLACEHOLDER, { className: "skill-name" }),
      meta,
      opsButtons(skill),
    );
    const detail = node("p", "", { className: "skill-desc" });
    if (skill.updated_at) detail.append(node("span", `${t("Updated", "更新于")} ${skill.updated_at} · `));
    detail.append(
      document.createTextNode(
        live && live.description ? String(live.description) : t("No description", "暂无描述"),
      ),
    );
    item.append(head, detail);
    const state = pending.get(name);
    const entry = notes.get(name);
    if (state || entry) {
      const info = node("p", "", { className: "skill-note" });
      if (state) {
        let message = `${t("Pending proposal", "待处理提案")}: ${state.proposal_id}`;
        if (state.decision) {
          message += ` · ${t("check", "检查")}: ${state.decision}`;
          if (state.reason_code) message += ` (${state.reason_code})`;
        }
        info.append(node("span", message, { className: "skill-proposal" }));
      }
      if (entry) {
        info.append(node("span", entry.message, { className: `skill-note-${entry.tone === "err" ? "err" : "ok"}` }));
      }
      item.append(info);
    }
    if (editorFor === name && versionFor !== name) item.append(editor(name));
    if (versionFor === name) item.append(versionPanel(skill));
    if (trajFor === name) item.append(trajectoryPanel(name));
    return item;
  }

  function paint() {
    if (context.signal?.aborted) return;
    if (!skills.length) {
      body.replaceChildren(
        node("p", t("No skills saved through self-evolution yet.", "尚未通过自演进保存技能。"), {
          className: "skill-empty",
        }),
      );
      pager.hidden = true;
      return;
    }
    const pages = pageCount();
    if (page >= pages) page = pages - 1;
    const catalog = new Map(skills.map((skill) => [skill.name == null ? "" : String(skill.name), skill.live]));
    const slice = skills.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
    body.replaceChildren(...slice.map((skill) => evolvedRow(skill, catalog)));
    pager.hidden = pages <= 1;
    prev.disabled = page <= 0;
    next.disabled = page >= pages - 1;
    indicator.textContent = `${page + 1} / ${pages}`;
  }

  prev.onclick = () => {
    page -= 1;
    paint();
    warmTrajectories();
  };
  next.onclick = () => {
    page += 1;
    paint();
    warmTrajectories();
  };
  pager.append(prev, indicator, next);
  card.append(body, pager);
  paint();

  async function refresh() {
    trajs.clear();
    let evolved;
    try {
      evolved = await fetchEvolved(context);
      if (context.signal?.aborted) return;
      // Fetch trajectories in parallel with live skill descriptions.
      trajs.warm(evolved.slice(0, PAGE_SIZE * 2).map((skill) => skill.name));
    } catch (error) {
      if (context.signal?.aborted) return;
      skills = [];
      page = 0;
      const code = error && error.message ? error.message : "INTERNAL";
      const message =
        code === "UNAVAILABLE"
          ? t("Self-evolution records are disabled: configure storage_path in the plugin config.", "自演进技能记录未启用：请在插件 config 中配置 storage_path。")
          : `${t("Could not load the self-evolved skills", "自演进技能列表加载失败")}: ${code}`;
      body.replaceChildren(node("p", message, { className: "skill-empty" }));
      pager.hidden = true;
      return;
    }
    let live = new Map();
    try {
      const catalog = await fetchSkills(context, context.signal);
      live = new Map(catalog.map((skill) => [skill.name == null ? "" : String(skill.name), skill]));
    } catch (error) {
      if (context.signal?.aborted) return;
      // The authorship list is still shown; only live descriptions degrade.
    }
    if (context.signal?.aborted) return;
    skills = evolved.map((skill) => ({ ...skill, live: live.get(skill.name == null ? "" : String(skill.name)) }));
    page = 0;
    paint();
    warmTrajectories();
  }

  context.signal?.addEventListener("abort", stopEvoPoll, { once: true });
  return { card, refresh, setOperations, setFeedbackMode };
}

// The grant-configuration card: pick which skills this plugin may evolve
// (target_skills). The choice lives in the operator's config.yaml;
// submitting rewrites the plugin's entry there and tells the caller to
// reinstall/restart — the running process never picks the change up live.
// Evolution model choice is deliberately NOT configured here: it is a
// per-launch selection in the trajectory panel's model picker.
export function createConfigureCard(context, options) {
  const t = (en, cn) => text(context, en, cn);
  const onModeChange = options && typeof options.onModeChange === "function" ? options.onModeChange : null;
  const card = node("section", "", { className: "status-card skill-config-card" });
  // Collapsed by default: the configuration is an occasional operator task,
  // not the page's primary content.
  const fold = node("details", "", { className: "status-fold skill-config-fold" });
  fold.append(node("summary", t("Plugin configuration", "插件配置"), { className: "status-fold-title" }));
  const inner = node("div", "", { className: "status-list" });
  inner.append(
    node(
      "p",
      t(
        "Choose the skills this plugin may evolve. Submitting writes them into config.yaml (host_access) and takes effect after a reinstall and Gateway restart.",
        "选择本插件可演进的技能。提交后将写入 config.yaml（host_access），重新安装并重启 Gateway 后生效。",
      ),
      { className: "skill-config-hint" },
    ),
  );
  const body = node("div", "", { className: "skill-config-body" });
  inner.append(body);
  fold.append(inner);
  card.append(createSectionHeading(
    t("Configuration", "配置"),
    t("Choose which skills can evolve and how feedback becomes a draft.", "选择参与演进的技能，设置反馈生成草案的方式。"),
  ), fold);

  let data = null;
  let catalog = [];
  let error = null;
  let saving = false;
  let result = null;
  // The free-text input is single-shot: one typed skill name, consumed on the
  // first successful add.
  let customUsed = false;
  let customError = null;
  // name -> checked
  const checkedSkills = new Map();

  function paintConfig() {
    body.replaceChildren();
    if (error) {
      body.append(node("p", `${t("Could not load the configuration", "配置加载失败")}: ${error}`, { className: "skill-config-error" }));
      return;
    }
    if (!data) {
      body.append(node("p", t("Loading configuration…", "正在读取配置…"), { className: "skill-config-hint" }));
      return;
    }
    if (!data.config_available) {
      body.append(node("p", t("config.yaml was not found or could not be read on this host.", "未找到或无法读取此宿主的 config.yaml。"), { className: "skill-config-error" }));
      return;
    }

    const skillsBox = node("div", "", { className: "skill-config-group" });
    skillsBox.append(node("h4", t("Target skills (target_skills)", "载入技能（target_skills）"), { className: "skill-config-group-title" }));
    const list = node("div", "", { className: "skill-config-options" });
    const names = orderTargetSkills(Array.isArray(data.skill_catalog) ? data.skill_catalog : [], data.targets || [], checkedSkills);
    for (const name of names) {
      const inTargets = (data.targets || []).includes(name);
      const live = catalog.find((skill) => skill && skill.name === name);
      const option = node("label", "", { className: "skill-config-option" });
      const box = node("input", "", { type: "checkbox", value: name });
      box.checked = checkedSkills.has(name) ? checkedSkills.get(name) : inTargets;
      checkedSkills.set(name, box.checked);
      box.onchange = () => checkedSkills.set(name, box.checked);
      option.append(box);
      const label = node("span", name, { className: "skill-config-option-name" });
      option.append(label);
      if (live && live.description) {
        option.append(node("span", String(live.description).slice(0, 120), { className: "skill-config-option-desc" }));
      } else if (!live) {
        option.append(node("span", t("not in catalog", "不在当前目录"), { className: "skill-config-option-missing" }));
      }
      list.append(option);
    }
    skillsBox.append(list);

    const inputRow = node("div", "", { className: "skill-config-input-row" });
    const input = node("input", "", { type: "text", className: "skill-config-input" });
    input.placeholder = t("Type a skill name to add…", "输入技能名添加…");
    if (customUsed) {
      input.disabled = true;
      input.placeholder = t("Free input used — submit to apply", "手动输入已用——提交后生效");
    }
    const add = node("button", t("Add", "添加"), { type: "button", className: "skill-op-btn" });
    add.disabled = customUsed;
    const consume = () => {
      const typed = input.value.trim();
      if (!typed) return;
      const match = names.find((name) => name === typed) || names.find((name) => name.toLowerCase() === typed.toLowerCase());
      if (!match) {
        customError = t(`Skill not found: ${typed}`, `技能不存在：${typed}`);
        paintConfig();
        return;
      }
      const box = list.querySelector(`input[value="${CSS.escape(match)}"]`);
      if (box) {
        box.checked = true;
        checkedSkills.set(match, true);
      }
      customError = null;
      customUsed = true;
      paintConfig();
    };
    add.onclick = consume;
    input.onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        consume();
      }
    };
    inputRow.append(input, add);
    skillsBox.append(inputRow);
    if (customError) skillsBox.append(node("p", customError, { className: "skill-config-error" }));
    skillsBox.append(
      node("p", t("Free input is single-shot: type one skill name, then submit once.", "手动输入仅一次：输入一个技能名后一次性提交。"), { className: "skill-config-note" }),
    );
    body.append(skillsBox);

    // Evolution mode: a peer of the target-skills group inside the same
    // fold. Persisted as JSON beside storage_path when configured, and
    // read per call, so saving it applies immediately — no restart.
    const modeBox = node("div", "", { className: "skill-config-group" });
    modeBox.append(node("h4", t("Evolution mode (evolution_mode)", "自演进方式（evolution_mode）"), { className: "skill-config-group-title" }));
    const currentMode = data.evolution_mode === "append" ? "append" : "model";
    const modeList = node("div", "", { className: "skill-config-options" });
    for (const mode of ["model", "append"]) {
      const option = node("label", "", { className: "skill-config-option" });
      const radio = node("input", "", { type: "radio", name: "skill-config-evolution-mode", value: mode });
      radio.checked = currentMode === mode;
      option.append(radio);
      option.append(
        node(
          "span",
          mode === "model"
            ? t("Model — a chat model drafts an evolution from your annotations", "模型——基于标注调用模型生成演进草案")
            : t("Append — feedback notes are appended directly to the skill content", "直接添加——把反馈备注直接追加到技能内容"),
          { className: "skill-config-option-name" },
        ),
      );
      modeList.append(option);
    }
    modeBox.append(modeList);
    modeBox.append(
      node(
        "p",
        t("Stored beside storage_path when configured, so extension upgrades preserve this choice; applies immediately after saving, no restart. Without storage_path, legacy install-local settings are used.", "已配置 storage_path 时，设置保存在数据库同目录，扩展升级后保留；保存后立即生效，无需重启。未配置时兼容使用安装目录设置。"),
        { className: "skill-config-note" },
      ),
    );
    body.append(modeBox);

    if (result) {
      const banner = node("div", "", { className: `skill-config-result ${result.ok ? "ok" : "err"}` });
      if (result.ok) {
        if (result.mode) {
          banner.append(
            node("p", t(`Evolution mode applied: ${result.mode === "append" ? "Append" : "Model"}.`, `自演进方式已生效：${result.mode === "append" ? "直接添加" : "模型"}。`)),
          );
        }
        if (result.targets) {
          banner.append(
            node("p", t("Configuration written to config.yaml. Reinstall and restart to apply:", "配置已写入 config.yaml，重新安装并重启后生效：")),
            node("code", result.reinstall_command || "make extension-upgrade SOURCE=examples/deerflow-extension-skill-evolution", { className: "skill-config-command" }),
            node("p", t("Then restart the Gateway.", "然后重启 Gateway。")),
          );
        }
      } else {
        banner.append(node("p", `${t("Could not write the configuration", "配置写入失败")}: ${result.error || "INTERNAL"}`));
      }
      body.append(banner);
    }

    const save = node("button", t("Save configuration", "保存配置"), { type: "button", className: "skill-op-btn skill-op-primary" });
    save.disabled = saving || !data.can_write;
    if (!data.can_write) {
      save.title = t("Your account is not in the skill_mutations owners grant.", "当前用户不在 skill_mutations owners 授权中。");
    }
    save.onclick = () => void submit();
    body.append(save);
  }

  async function submit() {
    if (saving) return;
    saving = true;
    result = null;
    paintConfig();
    const skillNames = [...checkedSkills.entries()].filter(([, checked]) => checked).map(([name]) => name);
    const selectedMode = body.querySelector('input[name="skill-config-evolution-mode"]:checked');
    const modeChanged = selectedMode && data && selectedMode.value !== (data.evolution_mode === "append" ? "append" : "model");
    const payload = { skill_names: skillNames };
    if (modeChanged) payload.evolution_mode = selectedMode.value;
    try {
      const response = await callAction(context, "skill_config_write", payload);
      if (response && response.ok) {
        result = { ok: true, reinstall_command: response.reinstall_command, mode: response.evolution_mode };
        data = { ...data, targets: response.targets || [], evolution_mode: response.evolution_mode || data.evolution_mode };
        // The mode is read per call on the backend, so reflect the new
        // behavior in the page immediately (evolution trigger vs draft
        // button) instead of waiting for a reload.
        if (response.evolution_mode && onModeChange) onModeChange(response.evolution_mode);
      } else {
        const code = response && response.error ? response.error.code || "INTERNAL" : "INTERNAL";
        const detail = response && response.error && Array.isArray(response.error.skills) ? `: ${response.error.skills.join(", ")}` : "";
        result = { ok: false, error: `${code}${detail}` };
      }
    } catch (error) {
      if (context.signal?.aborted) return;
      result = { ok: false, error: error && error.message ? error.message : "INTERNAL" };
    }
    saving = false;
    paintConfig();
  }

  async function refresh() {
    error = null;
    data = null;
    paintConfig();
    try {
      const [statusData, catalogData] = await Promise.all([
        callAction(context, "skill_config", {}),
        fetchSkills(context, context.signal).catch(() => []),
      ]);
      if (context.signal?.aborted) return;
      if (!statusData || statusData.ok !== true) {
        error = statusData && statusData.error ? statusData.error.code || "INTERNAL" : "INTERNAL";
      } else {
        data = statusData;
        catalog = catalogData;
      }
    } catch (caught) {
      if (context.signal?.aborted) return;
      error = caught && caught.message ? caught.message : "INTERNAL";
    }
    checkedSkills.clear();
    customUsed = false;
    customError = null;
    result = null;
    paintConfig();
  }

  fold.ontoggle = () => { if (fold.open) paintConfig(); };
  paintConfig();
  return { card, refresh };
}


function explainedRow(name, value, description, tone) {
  const item = row(name, value, tone);
  item.append(node("p", description, { className: "status-row-hint" }));
  return item;
}

function renderInformation(context, snapshot, root) {
  const t = (en, cn) => text(context, en, cn);
  const config = snapshot?.config || {};
  const host = snapshot?.host || {};
  const mutations = host.skill_mutations || {};
  const modelMode = config.evolution_mode ? config.evolution_mode === "model" : config.feedback_mode === "agent";
  const header = createSectionHeading(
    t("Information", "信息"),
    t("Understand agent guidance, current settings and the permissions this module needs.", "了解 Agent 的行为建议、当前演进方式，以及技能演进所需的运行条件与权限。"),
  );
  const identity = fold(t("Installation", "安装信息"), [
    row(t("Distribution", "发行包"), snapshot?.distribution || PLACEHOLDER),
    row(t("Version", "版本"), snapshot?.version || PLACEHOLDER),
    row(t("Namespace", "命名空间"), snapshot?.namespace || PLACEHOLDER),
  ]);
  const policy = fold(t("Agent behavior guidance", "Agent 行为建议"), [
    explainedRow(t("When to consider saving experience", "考虑沉淀经验的参考"),
      typeof config.min_tool_calls_hint === "number" ? t(`${config.min_tool_calls_hint}+ tool calls in a task`, `单次任务使用 ${config.min_tool_calls_hint} 次及以上工具`) : PLACEHOLDER,
      t("Prompt advice only: no counter or automatic evolution trigger. The agent decides after the task.", "仅为提示词建议：程序不会计数或自动启动演进，由 Agent 在任务后判断。")),
    explainedRow(t("Prefer small updates", "优先局部修改技能"), label(context, config.prefer_patch),
      t("Suggest targeted edits instead of rewriting the whole skill. Full rewrites remain possible.", "建议只修改需要改进的部分，避免不必要的整体重写；不是硬性限制。")),
    explainedRow(t("Ask before creating a skill", "创建新技能前询问用户"), label(context, config.confirm_before_create),
      t("A prompt instruction for new skills, not a program-enforced approval step.", "针对新建技能的提示词要求，不是程序强制审批，也不代表每次修改都要询问。")),
    explainedRow(t("Applies to", "适用 Agent"), label(context, config.scope),
      t("Which agents receive the extension's tools and guidance; configured in config.yaml.", "决定哪些 Agent 获得插件工具和行为建议，由 config.yaml 配置。")),
    explainedRow(t("Current evolution method", "当前演进方式"), modelMode ? t("Model-generated draft", "模型生成草案") : t("Append feedback", "直接追加反馈"),
      t("Saved in Plugin configuration and applied immediately. Publishing still follows the controlled pipeline.", "在上方“插件配置”中选择，保存后立即生效；发布变更仍经过暂存、检查和提交。")),
  ]);
  const evidence = host.completed_run_evidence || {};
  const chatModelsAvailable = host.chat_models === "available";
  const granted = (state) => state === "granted" ? "ok" : "muted";
  const capabilityRows = [
    node("p", t("These states report connected dependencies, not a guarantee that every operation will succeed. User, skill and model restrictions still apply.", "以下状态表示基础能力已接通，不保证每次操作成功；仍受用户、技能范围和模型授权限制。"), { className: "status-section-hint" }),
    explainedRow(t("Skill management tool", "技能管理工具"), label(context, host.skill_manage_tool),
      t("The host provides skill_manage to create or update skills, subject to authorization.", "宿主提供 skill_manage 工具，用于创建和修改技能，实际调用仍受权限约束。"), host.skill_manage_tool === "available" ? "ok" : "down"),
    explainedRow(t("Skill change permissions", "技能变更权限"), label(context, mutations.state || "not_granted"),
      t("Allows staged changes, checking, publishing and rollback for explicitly permitted users and skills.", "允许指定用户对指定技能执行暂存、检查、提交和回滚，来自 host_access.skill_mutations。"), granted(mutations.state)),
    explainedRow(t("Read completed task records", "历史任务记录读取权限"), label(context, evidence.state || "not_granted"),
      t("Reads sealed completed runs for trajectories, feedback and change provenance; granted through host_access.evidence.", "读取已结束并封存的任务记录，用于使用轨迹、反馈和变更来源追踪，来自 host_access.evidence。"), granted(evidence.state)),
    explainedRow(t("Stage / check / publish workflow", "暂存、检查与提交能力"), label(context, host.managed_pipeline),
      t("Derived from change permissions plus completed-run access; this is not a separate grant.", "由“技能变更权限”和“历史任务记录读取权限”共同决定，不是另一项独立授权。"), host.managed_pipeline === "available" ? "ok" : "muted"),
    explainedRow(t("Chat models", "对话模型"), label(context, chatModelsAvailable ? "available" : "unavailable"),
      t("Reuses chat model configuration and the current user permissions, with no additional plugin role grant.", "复用对话的模型配置和当前用户权限，无需单独填写插件模型授权。"), chatModelsAvailable ? "ok" : "muted"),
    explainedRow(t("Generate drafts from feedback", "根据反馈生成草案的能力"), label(context, host.evolution_jobs),
      t("Requires change, task-record and chat-model capabilities. Start with Confirm and improve in a skill's trajectories.", "需要技能变更、历史记录读取和对话模型三项能力；在技能轨迹中点击“确认并优化”启动。"), host.evolution_jobs === "available" ? "ok" : "muted"),
    explainedRow(t("Feedback storage", "反馈标注存储"), config.feedback_storage === "configured" ? t("Configured", "已配置") : t("Not configured", "未配置"),
      t("storage_path specifies the database used for annotations and evolution records.", "storage_path 指定存放反馈标注和演进记录的数据库。"), config.feedback_storage === "configured" ? "ok" : "warn"),
  ];
  const capabilities = fold(t("Runtime requirements and permissions", "运行条件与权限"), capabilityRows);
  const legacyOn = host.legacy_skill_evolution_enabled === true;
  const diagnostics = fold(t("Advanced diagnostics", "高级诊断"), [
    row(t("Granted operations", "授权操作"), Array.isArray(mutations.operations) ? mutations.operations.map((op) => OP_ORDER.includes(op) ? `${opLabel(context, op)} (${op})` : op).join(", ") : PLACEHOLDER),
    explainedRow(t("Interface protocol", "变更接口版本"), mutations.protocol_version || PLACEHOLDER,
      t("The interface version used by the extension and host; useful for compatibility troubleshooting.", "插件与宿主使用的变更接口版本，供兼容性排查使用。")),
    explainedRow(t("Deployment topology", "支持的部署方式"), mutations.topology || PLACEHOLDER,
      mutations.topology === "posix-single-host-local-filesystem"
        ? t("A single POSIX host with local files; not a multi-Gateway failover guarantee.", "POSIX 系统、单台宿主、本地文件系统；不代表支持多 Gateway 故障切换。")
        : t("Reported by the host; consult deployment documentation for supported layouts.", "由宿主报告，具体支持范围以部署文档为准。")),
    explainedRow(t("Legacy built-in implementation", "旧版内置演进功能"), label(context, legacyOn),
      legacyOn ? t("Also enabled: disable skill_evolution.enabled to avoid duplicate guidance.", "旧实现仍开启，可关闭 skill_evolution.enabled，避免重复的行为指导。")
        : t("The old implementation is off; the current extension can still evolve skills.", "关闭的是旧实现，不影响当前插件提供的技能演进能力。"), legacyOn ? "warn" : "ok"),
    mutations.capabilities === "unreadable" ? node("p", t("The service is connected, but its capability summary could not be read.", "服务已接通，但无法读取详细能力摘要。"), { className: "status-section-hint" }) : null,
  ]);
  const note = node("p", "", { className: "status-note" });
  note.append(
    node("strong", t("Permission changes require a Gateway restart; evolution mode applies immediately.", "权限配置需重启 Gateway；自演进方式切换立即生效。")),
    " ", t("Permissions are managed through config.yaml host_access; this information panel is read-only.", "权限由 config.yaml 的 host_access 配置；本信息区只展示状态。"),
  );
  root.replaceChildren(header, identity, policy, capabilities, diagnostics, note);
}

// Skill owns its refresh control, operational information and all related reads.
export function createSkillModule(context) {
  const t = (en, cn) => text(context, en, cn);
  const status = node("p", "", { role: "status", className: "status-notice" });
  const refresh = node("button", t("Refresh", "刷新"), {
    type: "button",
    className: "status-refresh",
  });
  const skills = createSkillsCard(context);
  const configure = createConfigureCard(context, {
    onModeChange: (mode) => skills.setFeedbackMode(mode === "append" ? "draft" : "agent"),
  });
  const statusRoot = node("section", "", { className: "evolution-information" });
  const content = node("div", "", { className: "skill-module-content" });
  content.append(status, skills.card, configure.card, statusRoot);
  let busy = false;

  async function load() {
    if (busy || context.signal?.aborted) return;
    busy = true;
    refresh.disabled = true;
    status.setAttribute("role", "status");
    status.textContent = t("Loading status…", "正在读取状态…");
    try {
      const snapshot = await context.callBackend("status", {});
      if (context.signal?.aborted) return;
      const mutations = snapshot && snapshot.host && snapshot.host.skill_mutations;
      skills.setOperations(
        mutations && mutations.state === "granted" && Array.isArray(mutations.operations) ? mutations.operations : [],
      );
      const snapshotConfig = (snapshot && snapshot.config) || {};
      skills.setFeedbackMode(
        snapshotConfig.evolution_mode
          ? snapshotConfig.evolution_mode === "model"
            ? "agent"
            : "draft"
          : snapshotConfig.feedback_mode,
      );
      renderInformation(context, snapshot, statusRoot);
      status.textContent = "";
    } catch (error) {
      if (context.signal?.aborted) return;
      status.textContent =
        error && error.message
          ? error.message
          : t("Could not load status.", "无法读取状态。");
      status.setAttribute("role", "alert");
    } finally {
      busy = false;
      refresh.disabled = false;
    }
  }

  refresh.onclick = () => {
    void load();
    void skills.refresh();
    void configure.refresh();
  };

  return {
    headerActions: refresh,
    content,
    start() {
      void load();
      void skills.refresh();
      void configure.refresh();
    },
  };
}
