// Original web adaptation of Pi's bookmark concept. No React/DeerFlow imports.
function mountBookmarks(root, context) {
  const zh = context.locale.startsWith("zh");
  const words = zh
    ? {
        heading: "留住值得再看的回答",
        description:
          "从会话菜单收藏回答，再回到这里查找。只有你可以访问这些书签。",
        search: "搜索书签",
        submit: "搜索",
        empty: "还没有匹配的书签",
        open: "返回会话",
        rename: "保存名称",
        remove: "删除",
        confirm: "确认删除",
        cancel: "取消",
        expand: "查看完整内容",
        loading: "正在加载…",
        error: "操作未完成，请重试。",
        label: "书签名称",
      }
    : {
        heading: "Keep answers worth returning to",
        description:
          "Save an answer from the conversation menu. Your bookmarks are private to your account.",
        search: "Search bookmarks",
        submit: "Search",
        empty: "No matching bookmarks",
        open: "Open conversation",
        rename: "Save name",
        remove: "Delete",
        confirm: "Confirm delete",
        cancel: "Cancel",
        expand: "Read full answer",
        loading: "Loading…",
        error: "Could not complete the action. Please retry.",
        label: "Bookmark name",
      };
  const make = (tag, content, attributes = {}) => {
    const element = document.createElement(tag);
    if (content) element.textContent = content;
    for (const [key, value] of Object.entries(attributes))
      element.setAttribute(key, value);
    return element;
  };
  const style = make(
    "style",
    `
    :host {display:block;color:inherit;font:inherit} * {box-sizing:border-box}
    .intro {padding:24px;background:linear-gradient(125deg,#edf9f4,#f1f4ff);border-radius:16px;color:#1b3930;margin-bottom:22px}
    h3 {font-size:23px;letter-spacing:-.5px;margin:0 0 8px} p {font-size:14px;line-height:1.7;margin:0}
    form {display:flex;gap:10px;margin:0 0 14px} input {font:inherit;color:inherit;background:transparent;border:1px solid #8885;border-radius:9px;padding:10px 12px;min-width:0;flex:1}
    button,a {font:inherit;font-size:13px;cursor:pointer;border:1px solid #8885;border-radius:8px;padding:8px 12px;background:transparent;color:inherit;text-decoration:none}
    button:disabled {opacity:.5;cursor:wait} button:hover,a:hover {background:#8881} .search-button {background:#216549;color:white} .search-button:hover {background:#194f39}
    article {border:1px solid #8884;border-radius:14px;padding:20px;margin:14px 0} .name {display:flex;gap:8px;flex-wrap:wrap;margin-bottom:15px}
    pre {white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:14px;line-height:1.8;margin:0 0 16px;max-height:320px;overflow:auto}
    .actions {display:flex;gap:9px;align-items:center;flex-wrap:wrap} .meta {font-size:12px;opacity:.6;margin-bottom:12px}
    [role=status],[role=alert] {font-size:13px;margin:8px 0} [role=alert] {color:#bd4040}
  `,
  );
  const intro = make("div", "", { class: "intro" });
  intro.append(make("h3", words.heading), make("p", words.description));
  const form = make("form");
  const query = make("input", "", {
    type: "search",
    placeholder: words.search,
    "aria-label": words.search,
    maxlength: "200",
  });
  const search = make("button", words.submit, {
    type: "submit",
    class: "search-button",
  });
  form.append(query, search);
  const status = make("p", "", { role: "status" });
  const error = make("p", "", { role: "alert" });
  const list = make("div");
  root.append(style, intro, form, status, error, list);
  let generation = 0;
  let disposed = false;
  const active = () => !disposed && !context.signal.aborted;
  async function run(button, operation) {
    button.disabled = true;
    error.textContent = "";
    try {
      await operation();
    } catch {
      if (active()) error.textContent = words.error;
    } finally {
      if (active()) button.disabled = false;
    }
  }
  async function load() {
    const current = ++generation;
    status.textContent = words.loading;
    try {
      const data = await context.callBackend("search", { query: query.value });
      if (!active() || current !== generation) return;
      status.textContent = data.total
        ? zh
          ? `共 ${data.total} 条 · 显示前 10 条，可搜索缩小范围`
          : `${data.total} saved · Showing up to 10; search to narrow results`
        : words.empty;
      list.replaceChildren();
      for (const item of data.items) {
        const card = make("article");
        const row = make("div", "", { class: "name" });
        const label = make("input", "", {
          "aria-label": words.label,
          maxlength: "120",
        });
        label.value = item.label;
        const rename = make("button", words.rename, { type: "button" });
        rename.addEventListener(
          "click",
          () =>
            void run(rename, async () => {
              await context.callBackend("rename", {
                id: item.id,
                label: label.value,
              });
              await load();
            }),
          { signal: context.signal },
        );
        row.append(label, rename);
        const content = make("pre", item.text);
        const actions = make("div", "", { class: "actions" });
        // The host resolves current routing metadata, including for old bookmarks.
        const open = make("button", words.open, { type: "button" });
        open.addEventListener(
          "click",
          () =>
            void run(open, async () => {
              if (!context.openConversation)
                throw new Error("Host conversation navigation is unavailable");
              await context.openConversation(item.thread_id);
            }),
          { signal: context.signal },
        );
        actions.append(open);
        if (item.truncated) {
          const expand = make("button", words.expand, { type: "button" });
          expand.addEventListener(
            "click",
            () =>
              void run(expand, async () => {
                const answer = await context.callBackend("get", {
                  id: item.id,
                });
                if (active()) {
                  content.textContent = answer.text;
                  expand.remove();
                }
              }),
            { signal: context.signal },
          );
          actions.append(expand);
        }
        const remove = make("button", words.remove, { type: "button" });
        const cancel = make("button", words.cancel, { type: "button" });
        cancel.hidden = true;
        cancel.addEventListener(
          "click",
          () => {
            remove.textContent = words.remove;
            cancel.hidden = true;
          },
          { signal: context.signal },
        );
        remove.addEventListener(
          "click",
          () => {
            if (cancel.hidden) {
              remove.textContent = words.confirm;
              cancel.hidden = false;
              return;
            }
            void run(remove, async () => {
              await context.callBackend("delete", { id: item.id });
              await load();
            });
          },
          { signal: context.signal },
        );
        actions.append(remove, cancel);
        card.append(
          row,
          make("div", item.created_at, { class: "meta" }),
          content,
          actions,
        );
        list.append(card);
      }
    } catch (cause) {
      if (active() && current === generation) status.textContent = "";
      throw cause;
    }
  }
  form.addEventListener(
    "submit",
    (event) => {
      event.preventDefault();
      void run(search, load);
    },
    { signal: context.signal },
  );
  void run(search, load);
  return {
    dispose() {
      disposed = true;
      generation++;
      root.replaceChildren();
    },
  };
}

export default {
  apiVersion: 1,
  module: "bookmarks.v1",
  icon: "bookmark",
  surfaces: [
    {
      id: "library",
      slot: "page",
      title: "Bookmarks",
      navigation: {
        label: "My bookmarks",
        labelZh: "我的书签",
        icon: "bookmark",
      },
      mount: mountBookmarks,
    },
  ],
  conversationActions(_t, locale = "en") {
    const zh = locale.startsWith("zh");
    return {
      label: zh ? "书签" : "Bookmarks",
      icon: "bookmark",
      actions: [
        {
          id: "save-answer",
          label: zh ? "收藏最后一条回答" : "Save last answer",
          icon: "bookmark",
          available: (settings) => settings.enabled === true,
          async execute(context, services) {
            const answer = await services.latestVisibleAnswer(context);
            if (!answer) {
              services.showMessage(
                zh ? "暂无可收藏的回答" : "No visible answer to save",
              );
              return;
            }
            if (answer.text.length > 12000) {
              services.showMessage(
                zh
                  ? "回答超过 12,000 字符，暂不支持收藏。"
                  : "Answers longer than 12,000 characters cannot be bookmarked yet.",
              );
              return;
            }
            await services.callBackend("save", {
              thread_id: context.thread.thread_id,
              message_id: answer.id,
              label: answer.text.replace(/\s+/g, " ").trim().slice(0, 80),
              text: answer.text,
            });
            services.showMessage(
              zh
                ? "已收藏，可从侧边栏打开“我的书签”查看"
                : "Saved. Open My bookmarks in the sidebar.",
            );
          },
        },
      ],
    };
  },
};
