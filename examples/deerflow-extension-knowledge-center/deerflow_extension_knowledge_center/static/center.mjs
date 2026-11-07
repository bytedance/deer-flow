import { copy } from "./copy.mjs";
import { mountLibrary } from "./library.mjs";

const API = "/api/extensions/knowledge-platform";
const enc = encodeURIComponent;
const MAX_FILE = 16 * 1024 * 1024;

// No host imports, provider credentials, persistence or automatic write retries.
export function mountCenter(root, context) {
  const w = copy[context.locale.startsWith("zh") ? "zh" : "en"];
  const make = (tag, text = "", attrs = {}) => {
    const node = document.createElement(tag);
    node.textContent = text;
    for (const [key, value] of Object.entries(attrs))
      node.setAttribute(key, value);
    return node;
  };
  const listen = (node, event, handler) =>
    node.addEventListener(event, handler, { signal: context.signal });
  const button = (text, handler) => {
    const node = make("button", text, { type: "button" });
    listen(node, "click", handler);
    return node;
  };
  const field = (label, node) => {
    const wrapper = make("label", label);
    wrapper.append(node);
    return wrapper;
  };
  const select = (label, items) => {
    const node = make("select", "", { "aria-label": label });
    for (const [value, text] of items)
      node.append(make("option", text, { value }));
    return node;
  };
  const style = make("link", "", {
    rel: "stylesheet",
    crossorigin: "use-credentials",
    href: new URL("./styles.css", import.meta.url).href,
  });
  const shell = make("div", "", { class: "center" });
  const status = make("p", "", { role: "status" });
  const error = make("p", "", { role: "alert", class: "error" });
  const spaces = select(w.space, []);
  const bases = select(w.base, []);
  const content = make("div");
  const reload = button(w.reload, () => void run(loadSpaces));
  const selectors = make("div", "", { class: "selectors" });
  selectors.append(field(w.space, spaces), field(w.base, bases), reload);
  shell.append(
    make("h2", w.heading),
    make("p", w.intro, { class: "intro" }),
    selectors,
    status,
    error,
    content,
  );
  root.append(style, shell);
  let disposed = false;
  let generation = 0;
  let controller = new AbortController();
  let busy = false;
  let dirty = false;
  let latestResources = [];
  // Selection-scoped only. No browser storage across accounts or visits.
  let records = new Map();
  const active = (g) =>
    !disposed && !context.signal.aborted && g === generation;
  const message = (cause) =>
    ({
      401: w.denied,
      403: w.denied,
      404: w.unavailable,
      409: w.conflict,
      422: w.invalid,
    })[cause.status] ?? w.failed;
  async function request(path, options = {}) {
    const response = await context.requestBackend(path, {
      ...options,
      signal: controller.signal,
    });
    if (!response.ok)
      throw Object.assign(new Error("Knowledge request failed"), {
        status: response.status,
      });
    return response.json();
  }
  async function run(operation) {
    error.textContent = "";
    const pending = operation();
    const g = generation;
    try {
      await pending;
    } catch (cause) {
      if (active(g) && cause.name !== "AbortError") {
        status.textContent = "";
        error.textContent = message(cause);
      }
    }
  }
  function reset() {
    controller.abort();
    controller = new AbortController();
    generation++;
    records = new Map();
    error.textContent = "";
    status.textContent = "";
    content.replaceChildren();
    dirty = false;
  }
  async function loadSpaces() {
    reset();
    const g = generation;
    spaces.disabled = bases.disabled = true;
    spaces.replaceChildren();
    bases.replaceChildren();
    status.textContent = w.loading;
    const data = await request(`${API}/spaces`);
    if (!active(g)) return;
    for (const item of data.items)
      spaces.append(make("option", item.title, { value: item.space_id }));
    spaces.disabled = data.items.length === 0;
    if (!data.items.length) {
      status.textContent = w.noSpaces;
      return;
    }
    await run(loadSpace);
  }
  async function loadSpace() {
    reset();
    const g = generation;
    bases.disabled = true;
    bases.replaceChildren();
    status.textContent = w.loading;
    const data = await request(`${API}/spaces/${enc(spaces.value)}`);
    if (!active(g)) return;
    for (const item of data.resources) {
      // The current platform projection has no human knowledge-base title.
      // Keep the exact native identifier visible instead of inventing one.
      bases.append(
        make("option", `${item.native_base_id} · ${item.connection_id}`, {
          value: item.resource_id,
        }),
      );
    }
    bases.disabled = data.resources.length === 0;
    latestResources = data.resources;
    if (!data.resources.length) {
      status.textContent = w.noBases;
      return;
    }
    await loadResource(data.resources);
  }
  async function loadResource(resources) {
    const item = resources.find((r) => r.resource_id === bases.value);
    if (!item) return;
    reset();
    const g = generation;
    const prefix = `${API}/spaces/${enc(spaces.value)}/resources/${enc(item.resource_id)}`;
    status.textContent = w.loading;
    const details = make("details");
    details.append(
      make("summary", w.details),
      make(
        "pre",
        JSON.stringify(
          {
            provider: item.provider,
            connection: item.connection_id,
            knowledge_base: item.native_base_id,
            dataset: item.dataset_id,
            processing: item.processing,
          },
          null,
          2,
        ),
      ),
    );
    content.append(details);
    const future = make("section", "", { class: "future" });
    future.append(make("h3", w.future), make("p", w.futureText));
    let capabilities;
    try {
      capabilities = await request(`${prefix}/capabilities`);
    } catch (cause) {
      if (!active(g)) return;
      status.textContent = "";
      content.append(
        make("p", cause.status === 403 ? w.browseOnly : message(cause)),
        future,
      );
      return;
    }
    if (!active(g)) return;
    status.textContent = "";
    const operations = new Set(capabilities.operations);
    const supported = new Set(capabilities.processing_options);
    const section = make("section");
    const taskSection = make("section");
    let uncertain = false;
    let readEpoch = 0;
    const readVersions = new Map();
    const warning = make("div", "", { class: "warning" });
    warning.hidden = true;
    const acknowledge = button(w.reconcile, () => {
      uncertain = false;
      warning.hidden = true;
      controls();
    });
    warning.append(make("p", w.uncertain), acknowledge);
    const mutationControls = [];
    const controls = () => {
      mutationControls.splice(
        0,
        mutationControls.length,
        ...mutationControls.filter((node) => content.contains(node)),
      );
      for (const node of mutationControls) node.disabled = busy || uncertain;
      spaces.disabled = bases.disabled = reload.disabled = busy || dirty;
    };
    const write = async (action, operation, accept = record) => {
      if (busy || uncertain || !active(g)) return;
      readEpoch++;
      busy = true;
      controls();
      error.textContent = "";
      let submitted = false;
      try {
        // Refresh capabilities before every explicit write; server admission is authoritative.
        const fresh = await request(`${prefix}/capabilities`);
        if (!active(g)) return;
        if (!fresh.operations.includes(action))
          throw Object.assign(new Error("Unsupported"), { status: 422 });
        submitted = true;
        const result = await operation();
        if (!active(g)) return;
        accept(result);
        status.textContent = action.startsWith("entry_")
          ? w.entrySaved
          : w.accepted;
      } catch (cause) {
        if (active(g) && cause.name !== "AbortError") {
          error.textContent = message(cause);
          if (submitted) {
            uncertain = true;
            warning.hidden = false;
          }
        }
      } finally {
        busy = false;
        if (active(g)) controls();
      }
    };
    const jsonWrite = (path, body) =>
      request(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    section.append(make("h3", w.import), warning);
    const kinds = ["manual", "url", "upload"].filter((kind) =>
      operations.has(kind),
    );
    if (kinds.length) {
      const form = make("form");
      const kind = select(
        w.import,
        kinds.map((k) => [k, w[k]]),
      );
      const title = make("input", "", { maxlength: "500" });
      const text = make("textarea", "", { rows: "7", maxlength: "1000000" });
      const url = make("input", "", { type: "url" });
      const file = make("input", "", { type: "file" });
      const titleField = field(w.title, title),
        textField = field(w.content, text),
        urlField = field(w.address, url),
        fileField = field(w.file, file);
      form.append(
        field(w.import, kind),
        titleField,
        textField,
        urlField,
        fileField,
      );
      const updateKind = () => {
        titleField.hidden = kind.value === "upload";
        textField.hidden = kind.value !== "manual";
        urlField.hidden = kind.value !== "url";
        fileField.hidden = kind.value !== "upload";
      };
      listen(kind, "change", updateKind);
      updateKind();
      const optionFields = new Map();
      const options = make("details");
      options.append(make("summary", w.options), make("p", w.defaults));
      for (const [key, label] of [
        ["summary_enabled", w.summary],
        ["graph_enabled", w.graph],
      ]) {
        if (!supported.has(key)) continue;
        const node = select(label, [
          ["", w.inherit],
          ["true", w.yes],
          ["false", w.no],
        ]);
        options.append(field(label, node));
        optionFields.set(key, node);
      }
      if (supported.has("chunk_size") && supported.has("chunk_overlap")) {
        for (const [key, label, min, max] of [
          ["chunk_size", w.chunkSize, 64, 8192],
          ["chunk_overlap", w.overlap, 0, 4096],
        ]) {
          const node = make("input", "", {
            type: "number",
            min,
            max,
            step: "1",
          });
          options.append(field(label, node));
          optionFields.set(key, node);
        }
      }
      form.append(options);
      const validation = make("p", "", { role: "alert", class: "error" });
      const submit = make("button", w.submit, {
        type: "submit",
        class: "primary",
      });
      mutationControls.push(submit);
      form.append(validation, submit);
      section.append(form);
      listen(form, "submit", (event) => {
        event.preventDefault();
        validation.textContent = "";
        const processing = {};
        for (const [key, node] of optionFields) {
          if (node.value !== "")
            processing[key] = key.startsWith("chunk_")
              ? Number(node.value)
              : node.value === "true";
        }
        const size = processing.chunk_size,
          overlap = processing.chunk_overlap;
        if (
          (size === undefined) !== (overlap === undefined) ||
          (size !== undefined &&
            (!Number.isInteger(size) ||
              size < 64 ||
              size > 8192 ||
              !Number.isInteger(overlap) ||
              overlap < 0 ||
              overlap > 4096 ||
              overlap >= size))
        ) {
          validation.textContent = w.badChunks;
          return;
        }
        const mode = kind.value;
        if (mode === "manual" && (!title.value.trim() || !text.value.trim())) {
          validation.textContent = w.required;
          return;
        }
        if (mode === "url") {
          try {
            const parsed = new URL(url.value);
            if (
              !["http:", "https:"].includes(parsed.protocol) ||
              parsed.username ||
              parsed.password ||
              parsed.hash
            )
              throw new Error();
          } catch {
            validation.textContent = w.badUrl;
            return;
          }
        }
        const selected = file.files?.[0];
        if (
          mode === "upload" &&
          (!selected || !selected.size || selected.size > MAX_FILE)
        ) {
          validation.textContent = w.fileSize;
          return;
        }
        const body = {
          kind: mode,
          title: title.value,
          processing,
          ...(mode === "manual" ? { content: text.value } : { url: url.value }),
        };
        // Serialize now, before async admission, so edits cannot alter the admitted request.
        const encoded = JSON.stringify(body);
        void write(mode, () =>
          mode === "upload"
            ? request(`${prefix}/files?filename=${enc(selected.name)}`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/octet-stream",
                  "X-Processing-Options": JSON.stringify(processing),
                },
                body: selected,
              })
            : request(`${prefix}/documents`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: encoded,
              }),
        );
      });
    } else section.append(make("p", w.noImport));
    taskSection.append(make("h3", w.tasks), make("p", w.taskIntro));
    const rows = make("div", "", { class: "records" });
    const record = (result) => {
      if (
        !result ||
        typeof result.document_id !== "string" ||
        result.provider !== item.provider ||
        result.connection_id !== item.connection_id ||
        result.dataset_id !== item.dataset_id
      )
        throw new Error("Invalid resource response");
      records.set(result.document_id, result);
      if (records.size > 50) records.delete(records.keys().next().value);
      renderRecords();
    };
    const lookup = async (id) => {
      if (busy) return;
      const epoch = readEpoch;
      const version = (readVersions.get(id) ?? 0) + 1;
      readVersions.set(id, version);
      const result = await request(`${prefix}/documents/${enc(id)}`);
      if (
        active(g) &&
        epoch === readEpoch &&
        version === readVersions.get(id) &&
        !busy
      )
        record(result);
    };
    if (operations.has("status")) {
      const form = make("form", "", { class: "lookup" });
      const id = make("input", "", { required: "", maxlength: "256" });
      const submit = make("button", w.lookup, { type: "submit" });
      form.append(field(w.document, id), submit);
      taskSection.append(form);
      listen(form, "submit", (event) => {
        event.preventDefault();
        if (!id.value.trim()) return;
        submit.disabled = true;
        void run(() => lookup(id.value.trim())).finally(() => {
          if (active(g)) submit.disabled = false;
        });
      });
    }
    function renderRecords() {
      rows.replaceChildren();
      mutationControls.splice(
        0,
        mutationControls.length,
        ...mutationControls.filter((node) => content.contains(node)),
      );
      for (const result of records.values()) {
        const row = make("article");
        const stateKey =
          result.state === "failed" ? "failedState" : result.state;
        const state = [
          "unknown",
          "queued",
          "running",
          "completed",
          "failedState",
          "cancelled",
        ].includes(stateKey)
          ? w[stateKey]
          : w.unknown;
        row.append(
          make("h4", result.document_id),
          make(
            "p",
            `${w.state}: ${state} · ${result.searchable === true ? w.searchable : w.notSearchable}`,
          ),
        );
        const raw = make("details");
        raw.append(
          make("summary", w.providerState),
          make("pre", String(result.provider_state)),
        );
        row.append(raw);
        const actions = make("div", "", { class: "actions" });
        if (operations.has("status"))
          actions.append(
            button(w.refresh, () => void run(() => lookup(result.document_id))),
          );
        for (const action of ["reprocess", "cancel"]) {
          if (!operations.has(action)) continue;
          const confirm = make("span", "", { class: "confirmation" });
          confirm.hidden = true;
          const trigger = button(w[action], () => {
            confirm.hidden = false;
          });
          const yes = button(w.confirm, () => {
            confirm.hidden = true;
            void write(action, () =>
              jsonWrite(
                `${prefix}/documents/${enc(result.document_id)}/${action}`,
                {},
              ),
            );
          });
          mutationControls.push(trigger, yes);
          confirm.append(
            make(
              "span",
              action === "cancel" ? w.confirmCancel : w.confirmReprocess,
            ),
            yes,
            button(w.back, () => {
              confirm.hidden = true;
            }),
          );
          actions.append(trigger, confirm);
        }
        row.append(actions);
        rows.append(row);
      }
      controls();
    }
    taskSection.append(rows, make("p", w.snapshots, { class: "note" }));
    future.replaceChildren();
    content.append(future, section, taskSection);
    mountLibrary(future, {
      locale: context.locale,
      make,
      button,
      field,
      listen,
      request,
      prefix,
      operations,
      active: () => active(g),
      run,
      write,
      controls,
      mutationControls,
      setDirty: (value) => {
        dirty = value;
        controls();
      },
      isBusy: () => busy,
      lookup,
      item,
      readEpoch: () => readEpoch,
      onTitle: (title) => {
        if (active(g) && title)
          bases.selectedOptions[0].textContent = `${title} · ${item.native_base_id} · ${item.connection_id}`;
      },
    });
    controls();
  }
  // One current-resource list; avoid accumulating handlers on repeated reloads.
  listen(spaces, "change", () => {
    if (!busy) void run(loadSpace);
  });
  listen(bases, "change", () => {
    if (!busy) void run(() => loadResource(latestResources));
  });
  if (!context.requestBackend) error.textContent = w.oldHost;
  else void run(loadSpaces);
  listen(window, "beforeunload", (event) => {
    if (dirty || busy) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  // Protect ordinary host-link navigation while an editor draft is present.
  document.addEventListener(
    "click",
    (event) => {
      const link = event
        .composedPath()
        .find((node) => node instanceof HTMLAnchorElement && node.href);
      if (
        link &&
        (busy ||
          (dirty &&
            !window.confirm(
              context.locale.startsWith("zh")
                ? "放弃尚未保存的条目修改？"
                : "Discard your unsaved entry changes?",
            )))
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    { capture: true, signal: context.signal },
  );
  return {
    dispose() {
      disposed = true;
      controller.abort();
      generation++;
      records.clear();
      root.replaceChildren();
    },
  };
}
