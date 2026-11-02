import { libraryCopy } from "./library-copy.mjs";
import { renderGraph } from "./graph.mjs";

export function mountLibrary(root, options) {
  const {
    locale,
    make,
    button,
    field,
    listen,
    request,
    prefix,
    operations,
    active,
    run,
    write,
    controls,
    mutationControls,
    setDirty,
    isBusy,
    lookup,
    item,
  } = options;
  const w = libraryCopy[locale.startsWith("zh") ? "zh" : "en"];
  const nav = make("div", "", {
    class: "library-nav",
    "aria-label": w.documents,
  });
  const panel = make("div");
  root.append(nav, panel);
  let selection = 0,
    reading = 0,
    dirty = false;
  let currentEntry = null;
  const markDirty = (value) => {
    dirty = value;
    setDirty(value);
  };
  const safeToLeave = () => !dirty || window.confirm(w.dirtyConfirm);
  function valid(result) {
    if (
      result.provider !== item.provider ||
      result.connection_id !== item.connection_id ||
      result.dataset_id !== item.dataset_id
    )
      throw new Error("Invalid resource identity");
    return result;
  }
  async function read(operation, query = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query))
      params.set(key, String(value));
    const result = valid(
      await request(`${prefix}/library/${operation}?${params}`),
    );
    if (active()) options.onTitle(result.title);
    return result;
  }
  async function readInto(target, operation, query, render) {
    if (isBusy() || !active()) return;
    const writeEpoch = options.readEpoch();
    const epoch = selection,
      version = ++reading;
    let settled = false;
    target.replaceChildren(make("p", w.loading, { role: "status" }));
    await run(async () => {
      const result = await read(operation, query);
      if (
        !active() ||
        epoch !== selection ||
        version !== reading ||
        writeEpoch !== options.readEpoch() ||
        isBusy()
      )
        return;
      target.replaceChildren();
      settled = true;
      render(result);
    });
    if (!settled && active() && epoch === selection && version === reading)
      target.replaceChildren();
  }
  for (const operation of ["documents", "entries", "graph"]) {
    const control = button(w[operation], () => show(operation));
    nav.append(control);
  }
  function show(operation) {
    if (isBusy() || !safeToLeave()) return;
    markDirty(false);
    selection++;
    reading++;
    currentEntry = null;
    panel.replaceChildren(make("h3", w[operation]));
    for (const [index, control] of [...nav.children].entries())
      control.setAttribute(
        "aria-pressed",
        String(["documents", "entries", "graph"][index] === operation),
      );
    if (!operations.has(operation)) {
      panel.append(make("p", w.unsupported));
      return;
    }
    if (operation === "graph") {
      graphForm();
      return;
    }
    panel.append(
      make("p", operation === "documents" ? w.documentNote : w.entriesNote, {
        class: "note",
      }),
    );
    const form = make("form", "", { class: "directory-search" });
    const search = make("input", "", { maxlength: "500", type: "search" });
    form.append(field(w.search, search));
    const state = make("select", "", { "aria-label": w.state });
    state.append(make("option", w.all, { value: "" }));
    for (const key of [
      "pending",
      "unprocessed",
      "processing",
      "parsing",
      "finalizing",
      "completed",
      "failed",
      "cancelled",
    ])
      state.append(make("option", w[key], { value: key }));
    if (operation === "documents") form.append(field(w.state, state));
    form.append(make("button", w.searchButton, { type: "submit" }));
    const results = make("div"),
      detail = make("div");
    panel.append(form, results, detail);
    let searchValue = "",
      stateValue = "";
    const load = (page) =>
      readInto(
        results,
        operation,
        { page, search: searchValue, state: stateValue },
        (result) => {
          const rows =
            operation === "documents" ? result.documents : result.entries;
          if (!rows.length) results.append(make("p", w.empty));
          for (const entry of rows) {
            const row = make("article");
            if (operation === "documents") {
              row.append(
                button(
                  entry.title || entry.processing.document_id,
                  () => void run(() => lookup(entry.processing.document_id)),
                ),
                make(
                  "p",
                  `${entry.processing.document_id} · ${entry.processing.provider_state}`,
                ),
              );
            } else {
              row.append(
                button(entry.title || entry.key, () => {
                  if (isBusy() || !safeToLeave()) return;
                  markDirty(false);
                  void readInto(
                    detail,
                    "entry",
                    { entry: entry.key },
                    (result) => renderEntry(detail, result.entry),
                  );
                }),
                make("p", `${entry.key} · ${w.version} ${entry.version}`),
              );
            }
            const open = row.querySelector("button");
            if (open)
              open.disabled = !operations.has(
                operation === "documents" ? "status" : "entry",
              );
            results.append(row);
          }
          const pagination = make("div", "", { class: "actions" });
          for (const [label, number, disabled] of [
            [w.previous, page - 1, page <= 1],
            [w.next, page + 1, page * result.page_size >= result.total],
          ]) {
            const control = button(label, () => {
              if (!safeToLeave()) return;
              markDirty(false);
              detail.replaceChildren();
              void load(number);
            });
            control.disabled = disabled;
            pagination.append(control);
          }
          pagination.append(make("span", `${page} · ${result.total}`));
          results.append(pagination);
        },
      );
    listen(form, "submit", (event) => {
      event.preventDefault();
      if (isBusy() || !safeToLeave()) return;
      markDirty(false);
      detail.replaceChildren();
      searchValue = search.value;
      stateValue = state.value;
      void load(1);
    });
    void load(1);
  }
  function renderEntry(target, entry) {
    if (
      !entry ||
      typeof entry.key !== "string" ||
      !Number.isInteger(entry.version) ||
      entry.version < 1
    )
      throw new Error("Invalid entry");
    currentEntry = entry;
    target.replaceChildren(
      make("h4", entry.title),
      make(
        "p",
        `${entry.key} · ${w.version} ${entry.version} · ${entry.status}`,
      ),
    );
    const title = make("input", "", { maxlength: "500" });
    title.value = entry.title;
    const content = make("textarea", "", { rows: "12", maxlength: "500000" });
    content.value = entry.content;
    title.readOnly = content.readOnly = !operations.has("entry_edit");
    // Lock the serialized draft for the entire capability/write round trip.
    if (operations.has("entry_edit")) mutationControls.push(title, content);
    const draft = make("p", "", { role: "status", class: "note" });
    const actions = make("div", "", { class: "actions" });
    const history = make("div");
    target.append(
      field(w.title, title),
      field(w.content, content),
      draft,
      actions,
      history,
    );
    const changed = () => {
      reading++; // Invalidate previews started before this draft changed.
      history.replaceChildren();
      markDirty(title.value !== entry.title || content.value !== entry.content);
      draft.textContent = dirty ? w.draft : "";
    };
    listen(title, "input", changed);
    listen(content, "input", changed);
    if (operations.has("entry_edit")) {
      const save = button(w.save, () => {
        if (!dirty || !title.value.trim()) return;
        reading++;
        const body = JSON.stringify({
          entry: entry.key,
          expected_version: entry.version,
          title: title.value,
          content: content.value,
        });
        void write(
          "entry_edit",
          () =>
            request(`${prefix}/entry`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body,
            }),
          (result) => {
            valid(result);
            markDirty(false);
            renderEntry(target, result.entry);
          },
        );
      });
      mutationControls.push(save);
      actions.append(save);
      actions.append(
        button(w.discard, () => {
          if (isBusy()) return;
          title.value = entry.title;
          content.value = entry.content;
          changed();
        }),
      );
    }
    if (operations.has("revisions"))
      actions.append(
        button(w.history, () => {
          if (dirty || isBusy()) return;
          void loadHistory(history, target, entry, 1);
        }),
      );
    controls();
  }
  async function loadHistory(history, target, entry, page) {
    await readInto(
      history,
      "revisions",
      { entry: entry.key, page },
      (result) => {
        if (currentEntry?.key !== entry.key) return;
        history.append(make("h4", w.history));
        if (!result.revisions.length) history.append(make("p", w.empty));
        const preview = make("div");
        for (const revision of result.revisions) {
          const row = make("article");
          row.append(
            make(
              "p",
              `${w.version} ${revision.version} · ${revision.editor} · ${revision.source} · ${revision.edited_at}`,
            ),
          );
          if (operations.has("revision"))
            row.append(
              button(`${w.view} ${revision.version}`, () => {
                if (dirty || isBusy()) return;
                void readInto(
                  preview,
                  "revision",
                  { entry: entry.key, version: revision.version },
                  (snapshot) => {
                    preview.append(
                      make(
                        "h4",
                        `${snapshot.entry.title} · ${w.version} ${snapshot.entry.version}`,
                      ),
                      make("pre", snapshot.entry.content),
                    );
                    if (!operations.has("entry_restore")) return;
                    const confirmation = make("div", "", {
                      class: "confirmation",
                    });
                    confirmation.hidden = true;
                    const restore = button(w.restore, () => {
                      confirmation.hidden = false;
                    });
                    const confirm = button(w.confirmRestore, () => {
                      reading++;
                      const body = JSON.stringify({
                        entry: entry.key,
                        expected_version: entry.version,
                        version: revision.version,
                      });
                      void write(
                        "entry_restore",
                        () =>
                          request(`${prefix}/entry/restore`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body,
                          }),
                        (result) => {
                          valid(result);
                          markDirty(false);
                          renderEntry(target, result.entry);
                        },
                      );
                    });
                    mutationControls.push(restore, confirm);
                    confirmation.append(
                      make("p", w.restoreNote),
                      confirm,
                      button(w.cancel, () => {
                        confirmation.hidden = true;
                      }),
                    );
                    preview.append(restore, confirmation);
                    controls();
                  },
                );
              }),
            );
          history.append(row);
        }
        const pages = make("div", "", { class: "actions" });
        for (const [label, number, disabled] of [
          [w.previous, page - 1, page <= 1],
          [w.next, page + 1, page * result.page_size >= result.total],
        ]) {
          const control = button(label, () => {
            if (!dirty) void loadHistory(history, target, entry, number);
          });
          control.disabled = disabled;
          pages.append(control);
        }
        history.append(pages, preview);
      },
    );
  }
  function graphForm() {
    const form = make("form", "", { class: "directory-search" });
    const query = make("input", "", { required: "", maxlength: "500" });
    const submit = make("button", w.graphButton, { type: "submit" });
    const result = make("div");
    form.append(field(w.graphQuery, query), submit);
    panel.append(form, result);
    listen(form, "submit", (event) => {
      event.preventDefault();
      if (!query.value.trim()) return;
      void readInto(result, "graph", { search: query.value }, (data) =>
        renderGraph(result, data.graph, { make, button, w }),
      );
    });
  }
  show(
    ["documents", "entries", "graph"].find((operation) =>
      operations.has(operation),
    ) ?? "documents",
  );
  return { isDirty: () => dirty };
}
