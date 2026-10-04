const zh = (context) => context.locale?.startsWith("zh");
const terminal = new Set(["completed", "failed", "cancelled"]);
function node(tag, text = "", attrs = {}) {
  const element = document.createElement(tag);
  element.textContent = text;
  Object.assign(element, attrs);
  return element;
}
// getRandomValues is available on the HTTP test deployments too.
function requestId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

function memberName(title, suffix = "") {
  let name = "";
  const encoder = new TextEncoder();
  for (const character of title.trim()) {
    const candidate = name + character + suffix;
    if (candidate.length > 80 || encoder.encode(candidate).length > 160) break;
    name += character;
  }
  return name.trimEnd() + suffix;
}

function mount(root, context) {
  const t = (en, cn) => (zh(context) ? cn : en);
  const controller = new AbortController();
  const sheet = node("link", "", {
    rel: "stylesheet",
    href: new URL("./style.css", import.meta.url).href,
  });
  const container = node("section", "", { className: "agent-teams" });
  const status = node("p", "", { role: "status", className: "notice" });
  const layout = node("div", "", { className: "team-layout" });
  const navigation = node("nav", "", {
    className: "team-navigation",
    ariaLabel: t("Teams", "团队列表"),
  });
  const content = node("div", "", { className: "team-content" });
  layout.append(navigation, content);
  container.append(
    node(
      "p",
      t(
        "A shared space for your agents to work together.",
        "让各有所长的 Agent 在同一个空间里协作。",
      ),
      { className: "intro" },
    ),
    status,
    layout,
  );
  root.append(sheet, container);
  let disposed = false,
    generation = 0,
    selected = null,
    teams = [],
    timer;
  const alive = (version) =>
    !disposed && !context.signal?.aborted && version === generation;
  const states = {
    queued: t("Queued", "排队中"),
    running: t("Running", "执行中"),
    resuming: t("Resuming", "恢复中"),
    cancelling: t("Cancelling", "取消中"),
    waiting_input: t("Needs input", "等待确认"),
    completed: t("Completed", "已完成"),
    failed: t("Failed", "失败"),
    cancelled: t("Cancelled", "已取消"),
  };
  async function call(action, payload) {
    const result = await context.callBackend(action, payload);
    if (disposed || context.signal?.aborted) throw new Error("View closed");
    return result;
  }
  function button(label, action, className = "") {
    const b = node("button", label, { type: "button", className });
    b.onclick = async () => {
      const version = generation;
      b.disabled = true;
      status.textContent = "";
      try {
        await action();
      } catch (error) {
        if (alive(version))
          status.textContent = error.message || t("Request failed", "请求失败");
      } finally {
        b.disabled = b.dataset.disabled === "true";
      }
    };
    return b;
  }
  function field(label, multiline = false) {
    const wrapper = node("label", label);
    const input = node(multiline ? "textarea" : "input", "", {
      required: true,
    });
    wrapper.append(input);
    return [wrapper, input];
  }
  function switchView() {
    clearTimeout(timer);
    status.textContent = "";
    return ++generation;
  }
  async function loadTeams() {
    teams = (await call("list", {})).teams;
    paintNavigation();
  }
  function paintNavigation() {
    navigation.replaceChildren(
      node("span", t("YOUR TEAMS", "我的团队"), { className: "eyebrow" }),
    );
    for (const team of teams) {
      const entry = button(
        "",
        async () => {
          selected = team.id;
          paintNavigation();
          await showTeam();
        },
        "team-link" + (selected === team.id ? " selected" : ""),
      );
      if (selected === team.id) entry.setAttribute("aria-current", "page");
      entry.append(
        node("span", team.name.slice(0, 1), { className: "avatar" }),
        node("span", team.name),
      );
      navigation.append(entry);
    }
    if (!teams.length)
      navigation.append(
        node(
          "p",
          t("Your teams will appear here.", "创建的团队会显示在这里。"),
          { className: "nav-empty" },
        ),
      );
    navigation.append(
      button(
        t("+ New team", "+ 新建团队"),
        async () => {
          selected = null;
          paintNavigation();
          await renderCreate();
        },
        "new-team",
      ),
    );
    const tip = node("div", "", { className: "nav-tip" });
    tip.append(
      node("strong", t("Work together with @", "用 @ 开始协作")),
      node(
        "p",
        t(
          "Choose who receives your request. Members can hand work to each other and return results here.",
          "选择任务的接收成员。成员可以继续交接工作，成果会汇集在这里。",
        ),
      ),
    );
    navigation.append(tip);
  }
  // The installed asset URL supplies the Gateway origin and any deployment prefix.
  // Use its existing authenticated public API; never import host application internals.
  async function catalog(version) {
    const url = new URL(import.meta.url);
    const marker = url.pathname.lastIndexOf("/api/plugins/");
    if (marker < 0)
      throw new Error(
        t(
          "Agent catalog requires packaged browser assets.",
          "成员目录需要通过插件资源服务加载。",
        ),
      );
    url.pathname = url.pathname.slice(0, marker) + "/api/agents";
    url.search = "";
    url.hash = "";
    const response = await fetch(url, {
      credentials: "include",
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok)
      throw new Error(
        t(
          `Cannot load agents (${response.status}). Check Agents access and retry.`,
          `无法加载 Agent（${response.status}），请检查 Agents 访问权限后重试。`,
        ),
      );
    const data = await response.json();
    // Recheck the host-bound viewer after the independent read, before displaying it.
    await call("list", {});
    if (!alive(version)) return [];
    if (!Array.isArray(data.agents))
      throw new Error(t("Invalid agent catalog", "Agent 列表格式异常"));
    return data.agents
      .filter((a) => typeof a.name === "string")
      .map((a) => ({
        name: a.name,
        title:
          typeof a.display_name === "string" && a.display_name
            ? a.display_name
            : a.name,
        description: typeof a.description === "string" ? a.description : "",
      }));
  }
  async function renderCreate() {
    const version = switchView();
    const form = node("form", "", { className: "panel create-panel" });
    const heading = node("header", "", { className: "panel-heading" });
    heading.append(
      node("h2", t("Build your team", "组建你的团队")),
      node(
        "p",
        t(
          "Choose existing agents and give them a shared goal.",
          "选好已有的 Agent，给他们一个共同目标。",
        ),
      ),
    );
    const body = node("div", "", { className: "form-body" });
    const [nameLabel, name] = field(t("Team name", "团队名称"));
    const [goalLabel, goal] = field(t("Shared goal", "共同目标"), true);
    name.maxLength = 80;
    goal.maxLength = 2000;
    name.placeholder = t("e.g. Product research", "例如：产品研究小组");
    goal.placeholder = t(
      "What should this team achieve together?",
      "希望这个团队一起完成什么？",
    );
    const catalogHeading = node("div", "", { className: "section-heading" });
    const count = node("span", "", { className: "muted" });
    catalogHeading.append(node("h3", t("Team members", "团队成员")), count);
    const search = node("input", "", {
      type: "search",
      placeholder: t(
        "Search agents by name or description",
        "搜索 Agent 名称或能力描述",
      ),
      ariaLabel: t("Search agents", "搜索 Agent"),
    });
    const catalogStatus = node("p", "", { className: "hint", role: "status" });
    const choices = node("div", "", { className: "agent-catalog" });
    const selection = node("div", "", {
      className: "selected-agents",
      ariaLabel: t("Selected agents", "已选成员"),
    });
    let agents = [],
      chosen = new Map(),
      loaded = false,
      loading = false;
    let createKey = requestId(),
      createPayload = "";
    const create = button(
      t("Create team", "创建团队"),
      async () => {
        if (!loaded || chosen.size < 2 || !form.reportValidity()) return;
        const picked = [...chosen.values()];
        const usedNames = new Set();
        const members = picked.map((agent) => {
          const title = agent.title.trim() || agent.name;
          let name = memberName(title);
          for (let number = 2; usedNames.has(name); number++) {
            name = memberName(title, ` (${number})`);
          }
          usedNames.add(name);
          return { name, agent: agent.name };
        });
        const payload = {
          name: name.value.trim(),
          goal: goal.value.trim(),
          members,
        };
        const fingerprint = JSON.stringify(payload);
        if (fingerprint !== createPayload) {
          createKey = requestId();
          createPayload = fingerprint;
        }
        const team = await call("create", {
          ...payload,
          request_id: createKey,
        });
        if (!alive(version)) return;
        selected = team.id;
        await loadTeams();
        if (alive(version)) await showTeam();
      },
      "primary",
    );
    function paintChoices() {
      if (!alive(version)) return;
      count.textContent = t(
        `${chosen.size} / 8 selected · at least 2`,
        `已选 ${chosen.size} / 8 位 · 至少 2 位`,
      );
      create.disabled = !loaded || chosen.size < 2;
      create.dataset.disabled = String(create.disabled);
      selection.replaceChildren();
      for (const agent of chosen.values())
        selection.append(
          button(
            `${agent.title} ×`,
            async () => {
              chosen.delete(agent.name);
              paintChoices();
            },
            "chip",
          ),
        );
      const query = search.value.trim().toLocaleLowerCase();
      choices.replaceChildren();
      const matches = agents.filter((a) =>
        `${a.title} ${a.name} ${a.description}`
          .toLocaleLowerCase()
          .includes(query),
      );
      for (const agent of matches) {
        const row = node("label", "", { className: "agent-option" });
        const checkbox = node("input", "", {
          type: "checkbox",
          checked: chosen.has(agent.name),
          disabled: !chosen.has(agent.name) && chosen.size >= 8,
          ariaLabel: agent.title,
        });
        checkbox.onchange = () => {
          if (checkbox.checked) chosen.set(agent.name, agent);
          else chosen.delete(agent.name);
          paintChoices();
        };
        const identity = node("span", "", { className: "agent-description" });
        identity.append(
          node("strong", agent.title),
          node("span", agent.description || agent.name, { className: "muted" }),
        );
        row.append(
          checkbox,
          node("span", agent.title.slice(0, 1), { className: "avatar" }),
          identity,
        );
        choices.append(row);
      }
      if (loaded && !matches.length)
        choices.append(
          node(
            "p",
            agents.length
              ? t("No matching agents.", "没有匹配的 Agent。")
              : t(
                  "Create at least two Custom Agents in Agents first, then reload this list.",
                  "请先在 Agents 中创建至少两个 Custom Agent，再重新加载列表。",
                ),
            { className: "empty-state" },
          ),
        );
    }
    async function loadCatalog() {
      if (loading) return;
      loading = true;
      loaded = false;
      paintChoices();
      catalogStatus.textContent = t(
        "Loading your agents…",
        "正在加载你的 Agent…",
      );
      try {
        agents = await catalog(version);
        if (!alive(version)) return;
        loaded = true;
        for (const key of chosen.keys())
          if (!agents.some((agent) => agent.name === key)) chosen.delete(key);
        catalogStatus.textContent = "";
      } catch (error) {
        if (alive(version)) catalogStatus.textContent = error.message;
      } finally {
        loading = false;
        paintChoices();
      }
    }
    search.oninput = paintChoices;
    body.append(
      nameLabel,
      goalLabel,
      catalogHeading,
      search,
      catalogStatus,
      choices,
      selection,
      button(t("Reload agents", "重新加载 Agent"), loadCatalog, "text-button"),
    );
    const footer = node("footer", "", { className: "form-footer" });
    footer.append(
      node(
        "span",
        t(
          "Each member keeps a separate conversation.",
          "每位成员保留独立的工作会话。",
        ),
        { className: "hint" },
      ),
      create,
    );
    form.append(heading, body, footer);
    form.onsubmit = (e) => {
      e.preventDefault();
      create.click();
    };
    content.replaceChildren(form);
    paintChoices();
    await loadCatalog();
  }

  async function showTeam() {
    const version = switchView();
    content.replaceChildren(
      node("p", t("Loading team…", "正在加载团队…"), { role: "status" }),
    );
    let team = await call("get", {
      team_id: selected,
      limit: 200,
      details: true,
    });
    if (!alive(version)) return;
    const workspace = node("div", "", { className: "team-workspace" });
    const header = node("header", "", { className: "workspace-heading" });
    const title = node("div");
    const syncStatus = node("span", "", {
      className: "sync-status",
      role: "status",
    });
    title.append(
      node("h2", team.name),
      node("p", team.goal, { className: "team-goal" }),
    );
    const settings = node("details", "", { className: "team-settings" });
    settings.append(node("summary", t("Manage", "管理")));
    const settingsBody = node("div", "", { className: "settings-menu" });
    settingsBody.append(
      button(t("Reconnect", "重新连接"), async () => {
        await call("connect", { team_id: team.id });
        await refresh();
      }),
      button(t("Refresh now", "立即刷新"), () => refresh()),
      button(
        t("Delete finished team", "删除已结束的团队"),
        async () => {
          if (
            !window.confirm(
              t(
                "Delete this team's records? Agent conversations are kept.",
                "删除团队记录？成员会话会保留。",
              ),
            )
          )
            return;
          await call("delete", { team_id: team.id });
          if (!alive(version)) return;
          selected = null;
          switchView();
          await loadTeams();
          if (!disposed) await renderCreate();
        },
        "danger",
      ),
    );
    settings.append(settingsBody);
    header.append(title, settings);
    const body = node("div", "", { className: "workspace-body" });
    const members = node("aside", "", {
      className: "workspace-members",
      ariaLabel: t("Team members", "团队成员"),
    });
    members.append(
      node("span", t("MEMBERS", "团队成员"), { className: "eyebrow" }),
    );
    const memberStates = new Map();
    const chat = node("div", "", { className: "team-chat" });
    const feed = node("div", "", {
      className: "message-feed",
      role: "region",
      ariaLabel: t("Team activity", "团队协作记录"),
    });
    const empty = node("div", "", { className: "chat-empty" });
    empty.append(
      node("span", "@", { className: "empty-symbol" }),
      node("h3", t("Start working together", "从第一项任务开始")),
      node(
        "p",
        t(
          "Mention a member below. Requests, handoffs and results will stay together here.",
          "在下方 @一位成员。请求、交接和结果都会汇集在这里。",
        ),
      ),
    );
    feed.append(empty);
    const composer = node("form", "", { className: "chat-composer" });
    const recipients = new Set();
    const chips = node("div", "", {
      className: "recipient-chips",
      ariaLabel: t("Recipients", "接收成员"),
    });
    const task = node("textarea", "", {
      maxLength: 4000,
      required: true,
      ariaLabel: t("Message to team", "发送给团队的消息"),
      placeholder: t(
        "@ a member and describe the work…",
        "@成员，描述需要完成的工作…",
      ),
    });
    const picker = node("div", "", {
      className: "mention-picker",
      role: "listbox",
      ariaLabel: t("Choose members", "选择成员"),
      hidden: true,
    });
    let mentionStart = null,
      candidates = [],
      cursor = 0,
      composing = false;
    const chooseButton = button(
      t("@ Choose members", "@ 选择成员"),
      async () => {
        mentionStart = null;
        showPicker("");
      },
    );
    chooseButton.setAttribute("aria-haspopup", "listbox");
    chooseButton.setAttribute("aria-expanded", "false");
    let draftKey = requestId(),
      sentFingerprint = "",
      sending = false;
    const send = button(
      t("Send", "发送"),
      async () => {
        if (sending) return;
        if (!recipients.size) {
          showPicker("");
          return;
        }
        if (!composer.reportValidity() || !task.value.trim()) return;
        const text = task.value.trim(),
          ids = [...recipients];
        const fingerprint = JSON.stringify([text, [...ids].sort()]);
        if (fingerprint !== sentFingerprint) {
          draftKey = requestId();
          sentFingerprint = fingerprint;
        }
        sending = true;
        try {
          // Stable per-recipient keys make partial network failures safe to retry.
          const outcomes = await Promise.allSettled(
            ids.map((id) =>
              call("send", {
                team_id: team.id,
                member_id: id,
                text,
                request_id: `${draftKey}:${id}`,
              }),
            ),
          );
          if (!alive(version)) return;
          const failed = outcomes.find((r) => r.status === "rejected");
          if (failed) throw failed.reason;
          if (
            task.value.trim() === text &&
            JSON.stringify([...recipients]) === JSON.stringify(ids)
          ) {
            task.value = "";
            recipients.clear();
            paintRecipients();
          }
          draftKey = requestId();
          sentFingerprint = "";
          await refresh();
        } finally {
          sending = false;
        }
      },
      "primary",
    );
    function hidePicker() {
      picker.hidden = true;
      chooseButton.setAttribute("aria-expanded", "false");
    }
    function paintRecipients() {
      chips.replaceChildren();
      for (const id of recipients) {
        const member = team.members.find((m) => m.id === id);
        const chip = button(
          `@${member.name} ×`,
          async () => {
            recipients.delete(id);
            paintRecipients();
          },
          "chip",
        );
        chip.setAttribute(
          "aria-label",
          t(`Remove recipient ${member.name}`, `移除接收成员 ${member.name}`),
        );
        chips.append(chip);
      }
    }
    function choose(member) {
      recipients.add(member.id);
      if (mentionStart !== null) {
        const end = task.selectionStart;
        task.setRangeText("", mentionStart, end, "end");
      }
      mentionStart = null;
      paintRecipients();
      hidePicker();
      task.focus();
    }
    function paintPicker() {
      picker.replaceChildren();
      if (!candidates.length)
        picker.append(
          node("p", t("No matching member", "没有匹配的成员"), {
            className: "hint",
          }),
        );
      candidates.forEach((member, index) => {
        const option = button(
          "",
          async () => choose(member),
          "mention-option" + (cursor === index ? " focused" : ""),
        );
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", String(index === cursor));
        option.append(
          node("span", member.name.slice(0, 1), { className: "avatar" }),
          node("span", `@${member.name}`),
          node("small", member.agent),
        );
        picker.append(option);
      });
    }
    function showPicker(query) {
      candidates = team.members.filter((m) =>
        `${m.name} ${m.agent}`
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()),
      );
      cursor = 0;
      picker.hidden = false;
      chooseButton.setAttribute("aria-expanded", "true");
      paintPicker();
    }
    task.oninput = () => {
      if (composing) return;
      const before = task.value.slice(0, task.selectionStart);
      const match = before.match(/(?:^|\s)@([^\s@]*)$/u);
      if (match) {
        mentionStart = before.lastIndexOf("@");
        showPicker(match[1]);
      } else {
        mentionStart = null;
        hidePicker();
      }
    };
    task.oncompositionstart = () => {
      composing = true;
      hidePicker();
    };
    task.oncompositionend = () => {
      composing = false;
      task.oninput();
    };
    task.onkeydown = (e) => {
      if (e.isComposing || composing) return;
      if (!picker.hidden && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        cursor =
          (cursor + (e.key === "ArrowDown" ? 1 : -1) + candidates.length) %
          (candidates.length || 1);
        paintPicker();
      } else if (!picker.hidden && e.key === "Enter") {
        e.preventDefault();
        if (candidates[cursor]) choose(candidates[cursor]);
      } else if (e.key === "Escape") hidePicker();
      else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        send.click();
      }
    };
    for (const member of team.members) {
      const memberRow = node("div", "", { className: "member-row" });
      const badge = node("span", t("Ready", "就绪"), {
        className: "member-state",
      });
      memberStates.set(member.id, badge);
      const selectMember = button(
        "",
        async () => {
          mentionStart = null;
          choose(member);
        },
        "member-pick",
      );
      const identity = node("span", "", { className: "member-identity" });
      identity.append(node("strong", member.name), badge);
      selectMember.append(
        node("span", member.name.slice(0, 1), { className: "avatar" }),
        identity,
      );
      selectMember.setAttribute(
        "aria-label",
        t(`Mention ${member.name}`, `提及 ${member.name}`),
      );
      const open = button(
        "↗",
        async () => context.openConversation?.(member.thread_id),
        "member-open",
      );
      open.setAttribute(
        "aria-label",
        t(`Open ${member.name} conversation`, `打开 ${member.name} 的会话`),
      );
      memberRow.append(selectMember, open);
      members.append(memberRow);
    }
    const composerFooter = node("div", "", { className: "composer-footer" });
    composerFooter.append(
      chooseButton,
      node("span", t("⌘ / Ctrl + Enter to send", "⌘ / Ctrl + Enter 发送"), {
        className: "hint",
      }),
      send,
    );
    composer.append(picker, chips, task, composerFooter);
    composer.onsubmit = (e) => {
      e.preventDefault();
      send.click();
    };
    const liveBar = node("div", "", { className: "live-bar" });
    liveBar.append(syncStatus);
    chat.append(feed, liveBar, composer);
    body.append(members, chat);
    workspace.append(header, body);
    content.replaceChildren(workspace);
    const cards = new Map();
    function dateLabel(value) {
      if (!value) return "";
      const date = new Date(value);
      return Number.isNaN(date.valueOf())
        ? ""
        : date.toLocaleString(context.locale || "en", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          });
    }
    function controlsFor(job) {
      const area = node("div", "", { className: "task-controls" });
      area.append(
        button(t("Open conversation", "打开完整会话"), async () =>
          context.openConversation?.(job.thread_id),
        ),
      );
      if (!terminal.has(job.status))
        area.append(
          button(t("Cancel task", "取消任务"), async () => {
            await call("cancel", { team_id: team.id, job_id: job.id });
            await refresh();
          }),
        );
      if (job.status === "waiting_input") {
        if (job.clarification)
          area.append(
            node("p", job.clarification.question, { className: "team-goal" }),
          );
        const [label, response] = field(
          job.clarification
            ? t("Your answer", "你的回答")
            : t(
                "Inspect the conversation, then enter the explicit response as JSON",
                "查看会话中的确认请求后，以 JSON 填写明确响应",
              ),
          true,
        );
        let resumeId = requestId(),
          responseSnapshot = "";
        area.append(
          label,
          button(t("Submit response", "提交响应"), async () => {
            const parsed = job.clarification
              ? response.value.trim()
              : JSON.parse(response.value);
            if (response.value !== responseSnapshot) {
              resumeId = requestId();
              responseSnapshot = response.value;
            }
            await call("resume", {
              team_id: team.id,
              job_id: job.id,
              response: parsed,
              request_id: resumeId,
            });
            await refresh();
          }),
        );
      }
      return area;
    }
    function renderCard(job) {
      let card = cards.get(job.id);
      if (!card) {
        const article = node("article", "", { className: "task-message" });
        article.dataset.jobId = job.id;
        const head = node("div", "", { className: "message-heading" });
        const route = node("strong"),
          badge = node("span"),
          time = node("time", "", { className: "muted" });
        head.append(route, time, badge);
        const request = node("p", "", { className: "request-text" });
        const parent = node("p", "", { className: "handoff-note" });
        const result = node("div", "", { className: "task-result" });
        const resultTitle = node("strong"),
          resultText = node("pre");
        result.append(resultTitle, resultText);
        const delivery = node("div", "", { className: "delivery" });
        const details = node("details", "", { className: "task-details" });
        const controls = node("div");
        details.append(
          node("summary", t("Task details", "任务详情")),
          controls,
        );
        article.append(head, parent, request, result, delivery, details);
        card = {
          article,
          route,
          badge,
          time,
          request,
          parent,
          result,
          resultTitle,
          resultText,
          delivery,
          controls,
          controlState: "",
          deliveryState: "",
        };
        cards.set(job.id, card);
        feed.append(article);
      }
      const member = team.members.find((m) => m.id === job.member_id);
      const source = team.members.find((m) => m.id === job.source_member_id);
      card.route.textContent = `${source?.name ?? t("You", "你")} → @${member?.name ?? "Agent"}`;
      card.badge.textContent = states[job.status] ?? job.status;
      card.badge.className = `badge ${job.status}`;
      card.time.textContent = dateLabel(job.created_at);
      card.request.textContent = job.text;
      const parentJob = team.jobs.find((j) => j.id === job.parent_id);
      card.parent.textContent = parentJob
        ? t(
            `Follow-up to: ${parentJob.text.slice(0, 100)}`,
            `接续任务：${parentJob.text.slice(0, 100)}`,
          )
        : "";
      card.result.hidden = !terminal.has(job.status);
      card.resultTitle.textContent =
        job.status === "completed"
          ? t(
              `${member?.name ?? "Agent"} · Result`,
              `${member?.name ?? "Agent"} · 执行结果`,
            )
          : states[job.status];
      card.resultText.textContent =
        job.result ||
        job.error ||
        t(
          "Result is no longer in the retained record. Open the original conversation.",
          "保留记录中没有结果，请打开原会话查看。",
        );
      if (card.controlState !== job.status) {
        card.controls.replaceChildren(controlsFor(job));
        card.controlState = job.status;
      }
      const deliveryState = JSON.stringify(job.delivery);
      if (card.deliveryState !== deliveryState) {
        card.deliveryState = deliveryState;
        card.delivery.replaceChildren();
        if (job.delivery) {
          const destination =
            source?.name ?? t("the original conversation", "原会话");
          card.delivery.append(
            node(
              "p",
              job.delivery.status === "completed"
                ? t(`Returned to ${destination}`, `结果已回到${destination}`)
                : t(
                    `Reply to ${destination}: ${states[job.delivery.status] ?? job.delivery.status}`,
                    `回传给${destination}：${states[job.delivery.status] ?? job.delivery.status}`,
                  ),
            ),
          );
          if (job.delivery.error)
            card.delivery.append(node("p", job.delivery.error));
          const details = node("details");
          details.append(
            node("summary", t("Reply details", "回传详情")),
            controlsFor(job.delivery),
          );
          card.delivery.append(details);
        }
      }
    }
    function paintActivity() {
      const nearBottom =
        feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
      const oldSize = cards.size;
      const requests = team.jobs.filter((job) => job.kind === "request");
      empty.hidden = requests.length > 0;
      for (const job of requests) renderCard(job);
      for (const member of team.members) {
        const jobs = team.jobs.filter((j) => j.thread_id === member.thread_id);
        const active =
          jobs.find((j) => j.status === "waiting_input") ??
          jobs.find((j) => !terminal.has(j.status));
        memberStates.get(member.id).textContent = active
          ? states[active.status]
          : t("Ready", "就绪");
      }
      syncStatus.textContent = team.connected
        ? t("● Live updates", "● 自动更新中")
        : t(
            "Disconnected · reconnect from Manage to continue queued work",
            "尚未连接 · 在管理中重新连接以继续待办任务",
          );
      if (nearBottom || !oldSize) feed.scrollTop = feed.scrollHeight;
    }
    let pending;
    async function refresh() {
      if (!alive(version)) return;
      if (pending) return pending;
      pending = (async () => {
        const current = await call("get", {
          team_id: team.id,
          limit: 200,
          details: true,
          revision: team.revision,
        });
        if (!alive(version)) return;
        if (!current.unchanged) {
          team = current;
          paintActivity();
        } else {
          syncStatus.textContent = team.connected
            ? t("● Live updates", "● 自动更新中")
            : t(
                "Disconnected · reconnect from Manage to continue queued work",
                "尚未连接 · 在管理中重新连接以继续待办任务",
              );
        }
      })();
      try {
        await pending;
      } finally {
        pending = null;
      }
    }
    async function poll() {
      if (!alive(version)) return;
      try {
        if (!document.hidden) await refresh();
      } catch {
        if (alive(version))
          syncStatus.textContent = t(
            "Updates interrupted · retrying automatically",
            "更新暂时中断，正在自动重试",
          );
      } finally {
        if (alive(version))
          timer = setTimeout(poll, document.hidden ? 10000 : 2000);
      }
    }
    paintActivity();
    timer = setTimeout(poll, 2000);
  }
  function dispose() {
    if (disposed) return;
    disposed = true;
    generation++;
    clearTimeout(timer);
    controller.abort();
    sheet.remove();
    container.remove();
    context.signal?.removeEventListener("abort", dispose);
  }
  context.signal?.addEventListener("abort", dispose, { once: true });
  loadTeams()
    .then(async () => {
      if (disposed) return;
      if (teams.length) {
        selected = teams[0].id;
        paintNavigation();
        await showTeam();
      } else await renderCreate();
    })
    .catch((error) => {
      if (!disposed) status.textContent = error.message;
    });
  return { dispose };
}

export default {
  apiVersion: 1,
  module: "agent-teams.v1",
  surfaces: [
    {
      id: "teams",
      slot: "page",
      title: "Agent teams",
      navigation: { label: "Agent teams", labelZh: "Agent 团队" },
      mount,
    },
  ],
  mentionProviders: [
    {
      id: "members",
      label: "Agent teams",
      async search(query, context) {
        return (await context.callBackend("search", { query })).items;
      },
    },
  ],
};
