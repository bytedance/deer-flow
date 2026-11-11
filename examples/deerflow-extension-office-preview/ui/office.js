import { highlightText, MAX_SEARCH_MATCHES } from "./search.js";
import { prepareOffice } from "./worker-client.js";
import { workbookViews } from "./workbook-view.js";
import { wordView } from "./word-view.js";

const styles = `
:host{display:block;height:100%;min-width:0}*{box-sizing:border-box}.office{height:100%;display:flex;flex-direction:column;font:13px system-ui,sans-serif;color:var(--foreground);background:var(--background)}
.bar,.tabs{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--border);flex-wrap:wrap}.bar button,.tabs button{color:inherit;background:var(--background);border:1px solid var(--border);border-radius:6px;min-width:28px;height:28px;cursor:pointer}.bar button:hover,.tabs button:hover{background:var(--accent)}button:focus-visible,input:focus-visible,td:focus-visible{outline:2px solid var(--ring);outline-offset:2px}.muted{color:var(--muted-foreground);font-size:12px}.spacer{flex:1}.bar input{min-width:80px;width:120px;background:var(--background);color:inherit;border:1px solid var(--border);border-radius:6px;padding:5px 7px}.canvas{flex:1;min-height:0;overflow:auto;background:var(--muted);padding:20px;overscroll-behavior:contain}.paper{width:max-content;min-width:100%;transform-origin:top left}.tabs{border-bottom:0;border-top:1px solid var(--border);padding:8px 12px;overflow:auto;flex-wrap:nowrap}.tabs button{white-space:nowrap;padding:3px 14px}.tabs button[aria-selected=true]{border-color:var(--ring);background:var(--accent);font-weight:600}.formula{padding:8px 12px;min-height:34px;border-bottom:1px solid var(--border);font-family:monospace;white-space:nowrap;overflow:auto}.table{border-collapse:separate;border-spacing:0;background:var(--background);table-layout:fixed;user-select:text}.table th,.table td{padding:8px 10px;min-width:90px;max-width:360px;height:32px;border-right:1px solid var(--border);border-bottom:1px solid var(--border);white-space:pre-wrap;overflow-wrap:anywhere}.table th{position:sticky;top:0;background:var(--muted);color:var(--muted-foreground);font:11px system-ui;z-index:1;text-align:center}.table th:first-child{left:0;min-width:42px;width:42px;z-index:2}.table td:focus{box-shadow:inset 0 0 0 2px var(--ring)}.note{padding:8px 12px;background:var(--accent);color:var(--accent-foreground);font-size:12px}.empty{padding:40px;text-align:center;color:var(--muted-foreground)}mark{background:#ffe478;color:#202020}.docx-wrapper{background:transparent!important;padding:0!important}.docx-wrapper>section.docx{box-shadow:0 2px 12px #0002;margin:0 auto 24px!important}.docx a{pointer-events:none;color:inherit;text-decoration:none}.slide{border:0;display:block;background:white;box-shadow:0 2px 12px #0002}.pages{display:flex;gap:8px;align-items:center}.slides-nav{display:flex;gap:6px;max-width:100%;overflow:auto}.slides-nav button{flex-shrink:0}.slides-nav button[aria-current=true]{outline:2px solid var(--ring)}
`;
const interactionStyles = `
button:disabled{opacity:.4;cursor:default}.bar button[aria-pressed=true]{background:var(--accent);border-color:var(--ring)}.cell-tools{display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--border);padding:6px 12px;flex-wrap:wrap}.cell-tools form{display:flex;align-items:center;gap:4px}.cell-tools input{width:74px;min-width:0;padding:6px;border:1px solid var(--border);border-radius:6px;background:var(--background);color:inherit;font:12px monospace}.cell-tools input[aria-invalid=true]{border-color:var(--destructive)}.cell-tools button{min-height:30px;background:var(--background);color:inherit;border:1px solid var(--border);border-radius:6px;padding:3px 8px;cursor:pointer}.cell-tools .formula{flex:1;min-width:100px;padding:4px;border:0;min-height:0}.cell-status{font-size:12px;color:var(--muted-foreground)}.table td[data-selected=true]{box-shadow:inset 0 0 0 2px var(--ring)}.canvas:focus-visible{outline:2px solid var(--ring);outline-offset:-2px}
`;
const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const button = (text, label, action) => {
  const node = element("button", "", text);
  node.type = "button";
  node.setAttribute("aria-label", label);
  node.title = label;
  node.addEventListener("click", action);
  return node;
};

export async function mountOffice(root, context) {
  const zh = context.locale.startsWith("zh");
  const tr = (en, cn) => (zh ? cn : en);
  const style = element("style");
  style.textContent =
    styles +
    interactionStyles +
    `
.reader-body{display:flex;flex:1;min-height:0;min-width:0}.reader-body>.canvas{min-width:0}.navigation{width:160px;flex-shrink:0;overflow:auto;padding:8px;border-right:1px solid var(--border);background:var(--background)}.navigation[hidden]{display:none}.navigation button{display:block;width:100%;text-align:left;padding:8px;margin-bottom:8px;border:1px solid var(--border);border-radius:6px;background:var(--background);color:inherit;cursor:pointer;overflow-wrap:anywhere}.navigation button[aria-current=true]{border-color:var(--ring);background:var(--accent)}.thumbnail{display:block;width:128px;height:72px;overflow:hidden;pointer-events:none;background:white;margin-bottom:6px}.thumbnail iframe{width:960px;height:540px;border:0;transform:scale(.1333333);transform-origin:top left}.find{display:flex;align-items:center;gap:6px;padding:8px 12px;flex-wrap:wrap;border-bottom:1px solid var(--border)}.find input{min-width:100px;flex:1;width:140px;background:var(--background);color:inherit;border:1px solid var(--border);border-radius:6px;padding:6px}.find button{border:1px solid var(--border);border-radius:6px;color:inherit;background:var(--background);min-width:30px;min-height:30px;cursor:pointer}.search-scope{flex-basis:100%;font-size:11px;color:var(--muted-foreground)}mark[data-current=true]{outline:2px solid var(--ring)}@media(max-width:600px){.navigation{width:120px}.thumbnail{width:96px;height:54px}.thumbnail iframe{transform:scale(.1)}}`;
  const shell = element("div", "office");
  shell.append(
    element("div", "empty", tr("Preparing preview…", "正在准备预览…")),
  );
  root.replaceChildren(style, shell);
  const kind = context.filename.split(".").pop().toLowerCase();
  const prepared = await prepareOffice(
    await context.readFile(),
    kind,
    context.signal,
  );
  context.signal.throwIfAborted();
  const saved = context.getReadingState?.();
  const reading = saved?.version === 1 ? saved : {};
  context.signal.throwIfAborted();
  shell.replaceChildren();
  const bar = element("div", "bar");
  bar.append(
    element(
      "strong",
      "",
      kind === "xlsx" ? "Excel" : kind === "docx" ? "Word" : "PowerPoint",
    ),
  );
  bar.append(
    element("span", "muted", tr("Preview", "预览")),
    element("span", "spacer"),
  );
  const canvas = element("div", "canvas");
  const paper = element("div", "paper");
  canvas.append(paper);
  const foot = element("div", "tabs");
  let zoom = 1;
  const zoomText = element("span", "muted", "100%");
  let fitting = false;
  const setZoom = (value, fit = false) => {
    const previousZoom = zoom;
    const left = canvas.scrollLeft,
      top = canvas.scrollTop;
    const atBottom =
      canvas.scrollHeight > canvas.clientHeight &&
      canvas.scrollHeight - top - canvas.clientHeight <= 2;
    fitting = fit;
    zoom = Math.max(0.25, Math.min(2, value));
    paper.style.zoom = String(zoom);
    zoomText.textContent = `${Math.round(zoom * 100)}%`;
    zoomOut.disabled = zoom <= 0.25;
    zoomIn.disabled = zoom >= 2;
    fitButton.setAttribute("aria-pressed", String(fitting));
    // Keep the same content under the viewport when its layout scale changes.
    if (previousZoom !== zoom)
      canvas.scrollTo(
        (left * zoom) / previousZoom,
        atBottom
          ? canvas.scrollHeight - canvas.clientHeight
          : (top * zoom) / previousZoom,
      );
  };
  const fitWidth = () => {
    const content = paper.querySelector(
      kind === "xlsx" ? "table" : kind === "docx" ? "section.docx" : "iframe",
    );
    setZoom(
      Math.min(
        1,
        Math.max(1, canvas.clientWidth - 40) / (content?.offsetWidth || 794),
      ),
      true,
    );
  };
  const zoomOut = button("−", tr("Zoom out", "缩小"), () =>
    setZoom(zoom - 0.1),
  );
  const zoomIn = button("+", tr("Zoom in", "放大"), () => setZoom(zoom + 0.1));
  const fitButton = button("↔", tr("Fit width", "适应宽度"), fitWidth);
  fitButton.setAttribute("aria-pressed", "false");
  bar.append(zoomOut, zoomText, zoomIn, fitButton);
  const body = element("div", "reader-body");
  body.append(canvas);
  shell.append(bar, body, foot);
  const disposals = [];
  let capture = () => ({});
  let ready = false;
  const save = () => {
    if (ready && !context.signal.aborted)
      context.saveReadingState?.({
        version: 1,
        zoom,
        fitting,
        scroll: [canvas.scrollLeft, canvas.scrollTop],
        ...capture(),
      });
  };
  canvas.addEventListener("scroll", () => queueMicrotask(save));
  bar.addEventListener("click", () => queueMicrotask(save));
  canvas.addEventListener("wheel", () => queueMicrotask(save));
  const find = element("div", "find");
  const query = element("input");
  query.type = "search";
  query.disabled = true;
  query.setAttribute("aria-label", tr("Find in file", "在文件中查找"));
  query.placeholder = tr("Find in file…", "在文件中查找…");
  const matchCount = element("span", "muted");
  matchCount.setAttribute("role", "status");
  matchCount.setAttribute("aria-label", tr("Search matches", "搜索匹配"));
  const scope = element(
    "span",
    "search-scope",
    kind === "xlsx"
      ? tr(
          "Search visible cells across all visible sheets, within the first 500 rows and 50 columns per sheet. Hidden cells and formulas are excluded.",
          "搜索所有可见工作表前 500 行、50 列中的可见单元格内容；不含隐藏单元格和公式。",
        )
      : kind === "docx"
        ? tr(
            "Search rendered document text; embedded objects are excluded.",
            "搜索已渲染的文档文字，不含嵌入对象。",
          )
        : tr(
            "Search slide text; text inside images, charts and embedded objects is excluded.",
            "搜索幻灯片文字，不含图片、图表和嵌入对象内的文字。",
          ),
  );
  scope.textContent += tr(
    " Shows up to 2,000 matches.",
    " 最多显示 2,000 处匹配。",
  );
  let matches = [],
    current = -1;
  let search = () => {};
  let searchTimer;
  const flushSearch = () => {
    if (searchTimer === undefined) return false;
    clearTimeout(searchTimer);
    searchTimer = undefined;
    search();
    return true;
  };
  disposals.push(() => clearTimeout(searchTimer));
  const updateMatches = (items) => {
    matches = items;
    current = -1;
    previousMatch.disabled = nextMatch.disabled = !items.length;
    matchCount.textContent = query.value
      ? tr(`${items.length} matches`, `${items.length} 处匹配`)
      : tr("Find text", "查找文字");
  };
  const moveMatch = (delta) => {
    if (!matches.length) return;
    current =
      current < 0
        ? delta < 0
          ? matches.length - 1
          : 0
        : (current + delta + matches.length) % matches.length;
    Promise.resolve(matches[current]()).catch(() => {
      if (!context.signal.aborted) context.onError();
    });
    matchCount.textContent = `${current + 1} / ${matches.length}`;
    save();
  };
  const previousMatch = button("↑", tr("Previous match", "上一处匹配"), () =>
    moveMatch(-1),
  );
  const nextMatch = button("↓", tr("Next match", "下一处匹配"), () =>
    moveMatch(1),
  );
  previousMatch.disabled = nextMatch.disabled = true;
  find.append(query, matchCount, previousMatch, nextMatch, scope);
  shell.insertBefore(find, body);
  query.addEventListener("input", () => {
    clearTimeout(searchTimer);
    updateMatches([]);
    searchTimer = setTimeout(() => {
      searchTimer = undefined;
      search();
      if (matches.length) moveMatch(1);
    }, 200);
  });
  query.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      flushSearch();
      moveMatch(event.shiftKey ? -1 : 1);
    }
    if (event.key === "Escape") {
      query.value = "";
      if (!flushSearch()) search();
    }
  });
  shell.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      query.focus();
      query.select();
    }
  });
  const reveal = (groups, index) => {
    paper
      .querySelectorAll("mark[data-current]")
      .forEach((mark) => delete mark.dataset.current);
    for (const mark of groups[index] ?? []) mark.dataset.current = "true";
    groups[index]?.[0]?.scrollIntoView({ block: "center", inline: "nearest" });
  };
  canvas.addEventListener(
    "wheel",
    (event) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        setZoom(zoom + (event.deltaY < 0 ? 0.1 : -0.1));
      }
    },
    { passive: false },
  );

  if (kind === "xlsx") {
    const sheets = workbookViews(prepared.sheets);
    const tools = element("div", "cell-tools");
    const jump = element("form");
    const address = element("input");
    address.setAttribute("aria-label", tr("Go to cell", "跳转到单元格"));
    address.placeholder = "A1";
    address.autocomplete = "off";
    address.maxLength = 12;
    const jumpButton = button(
      tr("Go", "跳转"),
      tr("Go to cell address", "跳转到单元格地址"),
      () => jump.requestSubmit(),
    );
    const formula = element("output", "formula");
    formula.setAttribute(
      "aria-label",
      tr("Cell value or formula", "单元格内容或公式"),
    );
    const status = element("span", "cell-status");
    status.setAttribute("role", "status");
    status.setAttribute(
      "aria-label",
      tr("Cell action status", "单元格操作状态"),
    );
    let selected;
    const copy = button(
      tr("Copy", "复制"),
      tr("Copy cell value", "复制单元格内容"),
      async () => {
        if (!selected) return;
        try {
          await navigator.clipboard.writeText(selected.text);
          if (!context.signal.aborted)
            status.textContent = tr("Copied", "已复制");
        } catch {
          if (!context.signal.aborted)
            status.textContent = tr(
              "Select the value to copy manually.",
              "请选择内容后手动复制。",
            );
        }
      },
    );
    copy.disabled = true;
    jump.append(address, jumpButton);
    tools.append(jump, formula, copy, status);
    shell.insertBefore(tools, body);
    const tablist = element("div", "slides-nav");
    tablist.setAttribute("role", "tablist");
    tablist.setAttribute("aria-label", tr("Worksheets", "工作表"));
    foot.append(tablist);
    const state = new Map(Array.isArray(reading.sheets) ? reading.sheets : []);
    let active;
    const paintSearch = () => {
      const groups = new Map();
      let remaining = MAX_SEARCH_MATCHES;
      const value = query.value.trim();
      const pattern = value
        ? new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "iu")
        : null;
      for (const td of paper.querySelectorAll("td")) {
        if (
          td.querySelector("mark[data-office-match]") ||
          pattern?.test(td.textContent)
        ) {
          const highlights = highlightText(td, value, remaining);
          remaining -= highlights.length;
          groups.set(td.dataset.address, highlights);
        }
      }
      return groups;
    };
    let sheetRevision = 0;
    const renderSheet = async (sheet) => {
      const revision = ++sheetRevision;
      context.signal.throwIfAborted();
      if (active)
        state.set(active.id, {
          scroll: [canvas.scrollLeft, canvas.scrollTop],
          address: selected?.address,
        });
      active = sheet;
      selected = undefined;
      formula.textContent = tr(
        "Select a cell to inspect its value or formula",
        "选择单元格查看内容或公式",
      );
      copy.disabled = true;
      address.value = "";
      status.textContent = "";
      address.removeAttribute("aria-invalid");
      for (const tab of tablist.children) {
        const current = tab.dataset.sheet === String(sheet.id);
        tab.setAttribute("aria-selected", String(current));
        tab.tabIndex = current ? 0 : -1;
      }
      paper.replaceChildren();
      const rows = Math.min(sheet.rowCount, 500),
        cols = Math.min(sheet.columnCount, 50);
      const table = element("table", "table");
      table.setAttribute("aria-label", sheet.name);
      const head = element("thead"),
        headers = element("tr");
      headers.append(element("th", "", ""));
      const letter = (column) => {
        let label = "";
        for (let n = column; n; n = Math.floor((n - 1) / 26))
          label = String.fromCharCode(65 + ((n - 1) % 26)) + label;
        return label;
      };
      for (let c = 1; c <= cols; c++) {
        if (!sheet.getColumn(c).hidden)
          headers.append(element("th", "", letter(c)));
      }
      head.append(headers);
      table.append(head);
      const tableBody = element("tbody");
      table.append(tableBody);
      if (rows && cols) paper.append(table);
      for (let r = 1; r <= rows; r++) {
        if (r % 16 === 0) {
          await new Promise((resolve) => setTimeout(resolve, 0));
          context.signal.throwIfAborted();
          if (revision !== sheetRevision) return;
        }
        const row = sheet.getRow(r);
        if (row.hidden) continue;
        const trNode = element("tr");
        trNode.append(element("th", "", String(r)));
        for (let c = 1; c <= cols; c++) {
          if (sheet.getColumn(c).hidden) continue;
          const cell = row.getCell(c);
          if (cell.isMerged && cell.master.address !== cell.address) continue;
          const td = element("td", "", cell.text);
          let rowEnd = r,
            colEnd = c;
          const merge = sheet._merges[`${r}:${c}`];
          if (merge) {
            const m = merge.model;
            if (m.top === r && m.left === c) {
              rowEnd = Math.min(m.bottom, rows);
              colEnd = Math.min(m.right, cols);
              td.rowSpan = Array.from(
                { length: rowEnd - r + 1 },
                (_, i) => r + i,
              ).filter((n) => !sheet.getRow(n).hidden).length;
              td.colSpan = Array.from(
                { length: colEnd - c + 1 },
                (_, i) => c + i,
              ).filter((n) => !sheet.getColumn(n).hidden).length;
            }
          }
          td.tabIndex = -1;
          td.dataset.address = cell.address;
          td.dataset.row = String(r);
          td.dataset.col = String(c);
          // Keep workbook coordinates separate from rendered spans, which exclude hidden rows/columns.
          td.dataset.rowEnd = String(rowEnd);
          td.dataset.colEnd = String(colEnd);
          td.style.width = `${Math.max(80, Math.min(360, (sheet.getColumn(c).width ?? 12) * 8))}px`;
          if (sheet.getColumn(c).hidden) td.hidden = true;
          td.style.fontWeight = cell.font?.bold ? "600" : "normal";
          td.style.fontStyle = cell.font?.italic ? "italic" : "normal";
          const color = cell.font?.color?.argb,
            fill = cell.fill?.fgColor?.argb;
          if (/^[A-Fa-f0-9]{8}$/.test(color ?? ""))
            td.style.color = `#${color.slice(2)}`;
          if (/^[A-Fa-f0-9]{8}$/.test(fill ?? ""))
            td.style.backgroundColor = `#${fill.slice(2)}`;
          if (["left", "center", "right"].includes(cell.alignment?.horizontal))
            td.style.textAlign = cell.alignment.horizontal;
          td.selectCell = () => {
            for (const previous of paper.querySelectorAll(
              "td[data-selected=true]",
            )) {
              previous.tabIndex = -1;
              delete previous.dataset.selected;
            }
            td.tabIndex = 0;
            td.dataset.selected = "true";
            selected = cell;
            copy.disabled = false;
            address.value = cell.address;
            address.removeAttribute("aria-invalid");
            status.textContent = "";
            formula.textContent = `${cell.address}   ${cell.formula ? `= ${cell.formula}   →   ` : ""}${cell.text}`;
          };
          td.addEventListener("focus", td.selectCell);
          trNode.append(td);
        }
        tableBody.append(trNode);
      }
      if (!rows || !cols)
        paper.append(
          element(
            "div",
            "empty",
            tr("This worksheet is empty.", "此工作表为空。"),
          ),
        );
      let note = shell.querySelector(".note");
      note?.remove();
      if (sheet.rowCount > rows || sheet.columnCount > cols) {
        note = element(
          "div",
          "note",
          tr(
            `Showing the first ${rows} rows and ${cols} columns. Download for the complete workbook.`,
            `仅预览前 ${rows} 行、${cols} 列，可下载完整工作簿。`,
          ),
        );
        shell.insertBefore(note, body);
      }
      const saved = state.get(sheet.id);
      const initial =
        (saved?.address &&
          paper.querySelector(`td[data-address="${saved.address}"]`)) ||
        paper.querySelector("td");
      initial?.selectCell();
      const scroll = saved?.scroll ?? [0, 0];
      canvas.scrollTo(scroll[0], scroll[1]);
      if (fitting) fitWidth();
      paintSearch();
      save();
    };
    for (const sheet of sheets) {
      const tab = button(sheet.name, sheet.name, () => {
        renderSheet(sheet).catch((error) => {
          if (!context.signal.aborted && error.name !== "AbortError")
            context.onError();
        });
      });
      tab.setAttribute("role", "tab");
      tab.dataset.sheet = String(sheet.id);
      tablist.append(tab);
    }
    if (sheets.length)
      await renderSheet(
        sheets.find((sheet) => sheet.id === reading.sheet) ?? sheets[0],
      );
    else
      paper.append(
        element(
          "div",
          "empty",
          tr("No visible worksheets.", "没有可见工作表。"),
        ),
      );
    capture = () => ({
      sheet: active?.id,
      sheets: [
        ...[...state.entries()].filter(([id]) => id !== active?.id),
        ...(active
          ? [
              [
                active.id,
                {
                  address: selected?.address,
                  scroll: [canvas.scrollLeft, canvas.scrollTop],
                },
              ],
            ]
          : []),
      ].slice(-50),
    });
    search = () => {
      const items = [];
      const value = query.value.trim();
      if (value) {
        const pattern = new RegExp(
          value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
          "giu",
        );
        searchCells: for (const sheet of sheets) {
          for (let row = 1; row <= Math.min(sheet.rowCount, 500); row++) {
            if (sheet.getRow(row).hidden) continue;
            for (let col = 1; col <= Math.min(sheet.columnCount, 50); col++) {
              if (sheet.getColumn(col).hidden) continue;
              const cell = sheet.getCell(row, col);
              if (cell.isMerged && cell.master.address !== cell.address)
                continue;
              let index = 0;
              for (const _match of cell.text.matchAll(pattern)) {
                if (items.length >= MAX_SEARCH_MATCHES) break searchCells;
                const occurrence = index++;
                items.push(async () => {
                  if (active !== sheet) await renderSheet(sheet);
                  if (context.signal.aborted || active !== sheet) return;
                  const groups = paintSearch().get(cell.address);
                  const td = paper.querySelector(
                    `td[data-address="${cell.address}"]`,
                  );
                  td?.selectCell();
                  reveal(groups ?? [], occurrence);
                });
              }
            }
          }
        }
      }
      paintSearch();
      updateMatches(items);
    };
    paper.addEventListener("focusin", () => queueMicrotask(save));
    jump.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = address.value.trim().toUpperCase();
      const match = /^([A-Z]{1,3})([1-9][0-9]{0,5})$/.exec(value);
      const row = match ? Number(match[2]) : 0;
      const col = match
        ? [...match[1]].reduce(
            (n, letter) => n * 26 + letter.charCodeAt(0) - 64,
            0,
          )
        : 0;
      const target =
        match &&
        [...paper.querySelectorAll("td")].find(
          (cell) =>
            Number(cell.dataset.row) <= row &&
            Number(cell.dataset.rowEnd) >= row &&
            Number(cell.dataset.col) <= col &&
            Number(cell.dataset.colEnd) >= col,
        );
      if (target) {
        target.focus();
        target.scrollIntoView({ block: "nearest", inline: "nearest" });
      } else {
        address.setAttribute("aria-invalid", "true");
        status.textContent = tr(
          "Cell is outside the visible preview.",
          "此单元格不在可见预览范围内。",
        );
      }
    });
    tablist.addEventListener("keydown", (event) => {
      const tabs = [...tablist.children],
        index = tabs.indexOf(event.target);
      if (
        index < 0 ||
        !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
      )
        return;
      event.preventDefault();
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : (index + (event.key === "ArrowLeft" ? -1 : 1) + tabs.length) %
              tabs.length;
      tabs[next].click();
      tabs[next].focus();
    });
    paper.addEventListener("keydown", (event) => {
      const delta = {
        ArrowUp: [-1, 0],
        ArrowDown: [1, 0],
        ArrowLeft: [0, -1],
        ArrowRight: [0, 1],
      }[event.key];
      const cell = event.target.closest("td");
      if (!delta || !cell) return;
      const cells = [...paper.querySelectorAll("td")];
      const row = Number(cell.dataset.row),
        col = Number(cell.dataset.col);
      const target = cells
        .filter((candidate) =>
          delta[0]
            ? Number(candidate.dataset.col) <= col &&
              Number(candidate.dataset.colEnd) >= col &&
              (Number(candidate.dataset.row) - row) * delta[0] > 0
            : Number(candidate.dataset.row) <= row &&
              Number(candidate.dataset.rowEnd) >= row &&
              (Number(candidate.dataset.col) - col) * delta[1] > 0,
        )
        .sort((a, b) =>
          delta[0]
            ? (Number(a.dataset.row) - Number(b.dataset.row)) * delta[0]
            : (Number(a.dataset.col) - Number(b.dataset.col)) * delta[1],
        )[0];
      event.preventDefault();
      if (target) {
        event.preventDefault();
        target.focus();
      }
    });
  } else if (kind === "docx") {
    const { renderDocument } = await import("docx-preview");
    const headings = prepared.headings;
    const view = wordView(prepared);
    disposals.push(() => view.dispose());
    const release = () => view.dispose();
    context.signal.addEventListener("abort", release, { once: true });
    disposals.push(() => context.signal.removeEventListener("abort", release));
    await new Promise((resolve) => setTimeout(resolve, 0));
    context.signal.throwIfAborted();
    try {
      await renderDocument(view.document, paper, paper, {
        inWrapper: true,
        breakPages: true,
        ignoreWidth: false,
        ignoreHeight: false,
        renderAltChunks: false,
        useBase64URL: false,
        ignoreFonts: true,
      });
    } catch (error) {
      view.dispose();
      throw error;
    }
    context.signal.throwIfAborted();
    paper
      .querySelectorAll("a")
      .forEach((anchor) => anchor.removeAttribute("href"));
    const pages = [...paper.querySelectorAll("section.docx")];
    const outline = element("nav", "navigation");
    outline.setAttribute("aria-label", tr("Document outline", "文档大纲"));
    body.prepend(outline);
    outline.hidden = reading.navigationOpen === false;
    const toggleOutline = button(
      tr("Outline", "大纲"),
      tr("Toggle document outline", "展开或收起文档大纲"),
      () => {
        outline.hidden = !outline.hidden;
        toggleOutline.setAttribute("aria-expanded", String(!outline.hidden));
        if (fitting) fitWidth();
        save();
      },
    );
    toggleOutline.setAttribute("aria-expanded", String(!outline.hidden));
    bar.insertBefore(toggleOutline, bar.children[2]);
    for (const heading of headings) {
      const target = paper.querySelector(`[id="${heading.id}"]`);
      if (!target) continue;
      const item = button(heading.title, heading.title, () => {
        canvas.scrollTop +=
          target.getBoundingClientRect().top -
          canvas.getBoundingClientRect().top -
          20;
        outline
          .querySelectorAll("button")
          .forEach((entry) =>
            entry.setAttribute("aria-current", String(entry === item)),
          );
        save();
      });
      item.style.paddingLeft = `${8 + heading.level * 10}px`;
      outline.append(item);
    }
    if (!outline.children.length)
      outline.append(
        element(
          "p",
          "muted",
          tr("No document headings.", "文档没有标题大纲。"),
        ),
      );
    const counter = element("span", "muted");
    let page = 0;
    counter.setAttribute("aria-live", "polite");
    const update = () => {
      counter.textContent = `${pages.length ? page + 1 : 0} / ${pages.length}`;
      previous.disabled = page <= 0;
      next.disabled = page >= pages.length - 1;
    };
    const go = (value) => {
      page = Math.max(0, Math.min(pages.length - 1, value));
      if (pages[page])
        canvas.scrollTop +=
          pages[page].getBoundingClientRect().top -
          canvas.getBoundingClientRect().top -
          20;
      update();
      save();
    };
    const previous = button("‹", tr("Previous page", "上一页"), () =>
      go(page - 1),
    );
    const next = button("›", tr("Next page", "下一页"), () => go(page + 1));
    foot.append(previous, counter, next);
    capture = () => ({ page, navigationOpen: !outline.hidden });
    search = () => {
      const groups = highlightText(paper, query.value.trim());
      updateMatches(groups.map((_, index) => () => reveal(groups, index)));
    };
    update();
    canvas.addEventListener("scroll", () => {
      const top = canvas.getBoundingClientRect().top + 24;
      let closest = 0;
      for (let i = 0; i < pages.length; i++)
        if (pages[i].getBoundingClientRect().top <= top) closest = i;
      if (
        canvas.scrollHeight > canvas.clientHeight &&
        canvas.scrollHeight - canvas.scrollTop - canvas.clientHeight <= 2
      )
        closest = pages.length - 1;
      if (closest !== page) {
        page = closest;
        update();
      }
    });
    fitWidth();
  } else {
    const slides = prepared.slides;
    context.signal.throwIfAborted();
    const frame = element("iframe", "slide");
    frame.width = "960";
    frame.height = "540";
    frame.setAttribute("sandbox", "");
    frame.setAttribute("title", context.filename);
    const stripActive = (html, highlight = false, match = -1) => {
      const doc = new DOMParser().parseFromString(html, "text/html");
      doc
        .querySelectorAll(
          "script,iframe,object,embed,link,base,meta,form,audio,video",
        )
        .forEach((node) => node.remove());
      doc.querySelectorAll("*").forEach((node) => {
        for (const attr of [...node.attributes]) {
          if (
            attr.name.startsWith("on") ||
            ["href", "srcdoc", "action"].includes(attr.name) ||
            (attr.name === "src" &&
              !/^data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,/i.test(
                attr.value,
              ))
          )
            node.removeAttribute(attr.name);
        }
      });
      // Converter text boxes contain anonymous flex text items. Keep each
      // contiguous inline run in one item before marks split its text nodes,
      // preserving the box's vertical alignment and the surrounding glyphs.
      for (const box of doc.querySelectorAll("div")) {
        if (!["flex", "inline-flex"].includes(box.style.display)) continue;
        let run = [];
        const wrap = () => {
          if (run.some((node) => node.textContent.trim())) {
            const line = doc.createElement("div");
            line.style.minWidth = "0";
            run[0].before(line);
            line.append(...run);
          }
          run = [];
        };
        for (const node of [...box.childNodes]) {
          if (
            node.nodeType === 3 ||
            /^(SPAN|B|I|U|S|EM|STRONG|BR|A|SUB|SUP)$/.test(node.nodeName)
          )
            run.push(node);
          else wrap();
        }
        wrap();
      }
      if (highlight) {
        const groups = highlightText(doc.body, query.value.trim());
        for (const mark of groups[match] ?? []) mark.dataset.current = "true";
      }
      return doc.body.innerHTML;
    };
    const counter = element("span", "muted");
    counter.setAttribute("aria-live", "polite");
    let page = 0;
    const nav = element("nav", "navigation");
    nav.setAttribute("aria-label", tr("Slide thumbnails", "幻灯片缩略图"));
    nav.hidden = reading.navigationOpen === false;
    body.prepend(nav);
    const toggleThumbnails = button(
      tr("Thumbnails", "缩略图"),
      tr("Toggle slide thumbnails", "展开或收起幻灯片缩略图"),
      () => {
        nav.hidden = !nav.hidden;
        toggleThumbnails.setAttribute("aria-expanded", String(!nav.hidden));
        if (fitting) fitWidth();
        save();
      },
    );
    toggleThumbnails.setAttribute("aria-expanded", String(!nav.hidden));
    bar.insertBefore(toggleThumbnails, bar.children[2]);
    const documentOf = (content) =>
      `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"><style>body{margin:0;overflow:hidden;background:white;color:black}mark{background:#ffe478;color:#202020}mark[data-current=true]{outline:2px solid #2665c7}</style></head><body>${content}</body></html>`;
    const go = (value, match = -1) => {
      page = Math.max(0, Math.min(slides.length - 1, value));
      frame.srcdoc = documentOf(stripActive(slides[page] ?? "", true, match));
      counter.textContent = `${page + 1} / ${slides.length}`;
      previous.disabled = page === 0;
      next.disabled = page === slides.length - 1;
      for (let i = 0; i < nav.children.length; i++)
        nav.children[i].setAttribute("aria-current", String(i === page));
      save();
    };
    const previous = button("‹", tr("Previous slide", "上一页"), () =>
      go(page - 1),
    );
    const next = button("›", tr("Next slide", "下一页"), () => go(page + 1));
    const thumbnailObserver = new IntersectionObserver(
      (items) => {
        if (context.signal.aborted) return;
        for (const item of items) {
          const target = item.target.querySelector(".thumbnail");
          if (item.isIntersecting && !target.children.length) {
            const preview = element("iframe");
            preview.setAttribute("sandbox", "");
            preview.tabIndex = -1;
            preview.setAttribute("aria-hidden", "true");
            preview.srcdoc = documentOf(
              stripActive(slides[Number(item.target.dataset.slide)]),
            );
            target.append(preview);
          } else if (!item.isIntersecting) target.replaceChildren();
        }
      },
      { root: nav, rootMargin: "100px" },
    );
    disposals.push(() => thumbnailObserver.disconnect());
    for (let i = 0; i < slides.length; i++) {
      const item = button("", tr(`Slide ${i + 1}`, `第 ${i + 1} 页`), () =>
        go(i),
      );
      item.dataset.slide = String(i);
      item.append(
        element("span", "thumbnail"),
        element("span", "muted", String(i + 1)),
      );
      nav.append(item);
      thumbnailObserver.observe(item);
    }
    paper.append(frame);
    foot.append(previous, counter, next);
    capture = () => ({ page, navigationOpen: !nav.hidden });
    search = () => {
      const items = [];
      slides.forEach((slide, index) => {
        if (items.length >= MAX_SEARCH_MATCHES) return;
        const doc = new DOMParser().parseFromString(
          stripActive(slide),
          "text/html",
        );
        const groups = highlightText(
          doc.body,
          query.value.trim(),
          MAX_SEARCH_MATCHES - items.length,
        );
        groups.forEach((_, match) => items.push(() => go(index, match)));
      });
      updateMatches(items);
      go(page);
    };
    canvas.tabIndex = 0;
    canvas.setAttribute(
      "aria-label",
      tr(
        "Slide preview. Use arrow keys to change slides.",
        "幻灯片预览，可使用方向键翻页。",
      ),
    );
    shell.addEventListener("keydown", (event) => {
      if (
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        event.target.closest(".bar,.find,input,textarea")
      )
        return;
      const value = {
        ArrowLeft: page - 1,
        ArrowUp: page - 1,
        PageUp: page - 1,
        ArrowRight: page + 1,
        ArrowDown: page + 1,
        PageDown: page + 1,
        Home: 0,
        End: slides.length - 1,
      }[event.key];
      if (value === undefined) return;
      event.preventDefault();
      go(value);
    });
    if (slides.length) go(Number.isInteger(reading.page) ? reading.page : 0);
    else throw new Error("Empty presentation");
    fitWidth();
  }
  if (Number.isFinite(reading.zoom)) {
    if (reading.fitting) fitWidth();
    else setZoom(reading.zoom);
  }
  if (Array.isArray(reading.scroll) && reading.scroll.every(Number.isFinite))
    canvas.scrollTo(reading.scroll[0], reading.scroll[1]);
  ready = true;
  query.disabled = false;
  save();
  const observer = new ResizeObserver(() => {
    if (fitting && !context.signal.aborted) fitWidth();
  });
  observer.observe(canvas);
  disposals.push(() => observer.disconnect());
  if (context.signal.aborted) {
    root.replaceChildren();
    return () => {};
  }
  return () => {
    for (const dispose of disposals) dispose();
    root.replaceChildren();
  };
}
