import test, { after } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Match the host asset URL layout used by endpoint(), with all fetches mocked.
const temp = await mkdtemp(join(tmpdir(), "trajectory-turns-"));
await mkdir(join(temp, "api/plugins"), {recursive:true});
const entry = join(temp, "api/plugins/index.mjs");
const source = await readFile(new URL("../deerflow_extension_trajectory/static/dist/index.mjs", import.meta.url), "utf8");
await writeFile(entry, source.replace("import.meta.url", '"https://trajectory.test/api/plugins/assets/index.mjs"'));
after(() => rm(temp, {recursive:true, force:true}));
const {default:extension, TurnBuffer, imageEndpoint, durationLabel, analyzeRows} = await import(pathToFileURL(entry));

test("image URLs stay on the Gateway and encode the thread and path segments", () => {
  assert.equal(imageEndpoint("thread 1", "/mnt/user-data/uploads/photo #1.png").href, "https://trajectory.test/api/threads/thread%201/artifacts/mnt/user-data/uploads/photo%20%231.png");
  for (const path of ["/etc/a.png", "/mnt/user-data/uploads/../a.png", "/mnt/user-data/uploads/a.svg", "https://evil.test/a.png"]) assert.throws(() => imageEndpoint("t", path));
});

const row = (id, kind = "assistant", extra = {}) => ({row_id:id, id, kind, text:id, created_at:"2026-10-23T00:00:00Z", ...extra});

test("a long turn spans empty pages and stops at its user boundary", () => {
  const buffer = new TurnBuffer();
  buffer.add({rows:[row("answer")], next_cursor:"a"});
  assert.equal(buffer.takeTurn(), null);
  buffer.add({rows:[], next_cursor:"b"});
  assert.equal(buffer.takeTurn(), null);
  buffer.add({rows:[row("older", "user"), row("old-answer"), row("new", "user"), row("tool", "tool")], next_cursor:"c"});
  assert.deepEqual(buffer.takeTurn().map(r => r.row_id), ["new", "tool", "answer"]);
  assert.deepEqual(buffer.takeTurn().map(r => r.row_id), ["older", "old-answer"]);
  assert.equal(buffer.hasMore, true);
});

test("multiple turns in one final page remain separately available", () => {
  const buffer = new TurnBuffer();
  buffer.add({rows:[row("u1", "user"), row("a1"), row("u2", "user"), row("a2")], next_cursor:null});
  assert.deepEqual(buffer.takeTurn().map(r => r.row_id), ["u2", "a2"]);
  assert.equal(buffer.hasMore, true);
  assert.deepEqual(buffer.takeTurn().map(r => r.row_id), ["u1", "a1"]);
  assert.equal(buffer.hasMore, false);
});

test("updated user messages do not split turns; overlap does not duplicate rows", () => {
  const buffer = new TurnBuffer();
  buffer.add({rows:[row("update", "user", {updated:true}), row("a")], next_cursor:"a"});
  assert.equal(buffer.takeTurn(), null);
  buffer.add({rows:[row("u", "user"), row("update", "user", {updated:true})], next_cursor:null});
  assert.deepEqual(buffer.takeTurn().map(r => r.row_id), ["u", "update", "a"]);
});

test("missing user boundary is retained as partial history only at exhaustion", () => {
  const buffer = new TurnBuffer();
  buffer.add({rows:[row("orphan", "tool")], next_cursor:"a"});
  assert.equal(buffer.takeTurn(), null);
  buffer.add({rows:[], next_cursor:null});
  assert.deepEqual(buffer.takeTurn().map(r => r.row_id), ["orphan"]);
  assert.equal(buffer.takeTurn(), null);
  assert.equal(buffer.hasMore, false);
});

// Exercise the actual page controller without a browser or network.
class Node {
  children = []; handlers = {}; attributes = {}; textContent = "";
  append(child) { child.parent = this; this.children.push(child); }
  replaceChildren(...children) { this.children = []; for (const child of children) this.append(child); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { const prior = this.handlers[name]; this.handlers[name] = (...args) => {prior?.(...args); callback(...args);}; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  remove() {}
  click() { if (!this.disabled) this.handlers.click?.(); }
}
const nodes = root => [root, ...root.children.flatMap(nodes)];
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(resolve => setImmediate(resolve)); };

test("a failed history refresh can be retried", async () => {
  const saved = {document:globalThis.document, window:globalThis.window, fetch:globalThis.fetch};
  let fail = false;
  globalThis.document = {createElement:() => new Node()};
  globalThis.window = {location:{search:"?thread_id=test"}};
  const pages = [
    {rows:[row("a3")], next_cursor:"older"},
    {rows:[row("u1", "user"), row("a1"), row("u2", "user"), row("a2"), row("u3", "user")], next_cursor:null},
  ];
  globalThis.fetch = async url => {
    if (fail) throw new Error("temporary failure");
    return {ok:true, json:async () => pages[url.searchParams.has("cursor") ? 1 : 0]};
  };
  const root = new Node();
  let mounted;
  try {
    mounted = extension.surfaces[0].mount(root, {locale:"zh-CN", signal:new AbortController().signal});
    await settle();
    const thresholds = nodes(root).filter(n => n.type === "number");
    assert.deepEqual(thresholds.map(input => input.placeholder), ["默认无限制", "默认无限制"]);
    const refresh = () => nodes(root).find(n => n.textContent === "最新一轮").click();
    fail = true;
    refresh(); await settle();
    assert(nodes(root).some(n => n.textContent.includes("temporary failure")));
    fail = false;
    refresh(); await settle();
    assert(nodes(root).some(n => n.className === "trajectory-preview" && n.textContent === "a3"));
  } finally {
    mounted?.dispose();
    Object.assign(globalThis, saved);
  }
});

test("export reports failures and revokes its download URL on disposal", async () => {
  const saved = {document:globalThis.document, window:globalThis.window, fetch:globalThis.fetch};
  const root = new Node(), anchors = [];
  let mounted, fail = false, exports = 0;
  globalThis.document = {createElement:tag => {
    const node = new Node();
    if (tag === "a") anchors.push(node);
    return node;
  }};
  globalThis.window = {location:{search:"?thread_id=owner-thread"}};
  globalThis.fetch = async (url, options) => {
    if (url.pathname.endsWith("/export")) {
      exports++;
      assert.equal(options.credentials, "include");
      assert.equal(url.searchParams.get("format"), "markdown");
      if (fail) return new Response(JSON.stringify({detail:"对话无权访问"}), {status:403});
      return new Response("zip content", {headers:{"X-Trajectory-Warnings":"1"}});
    }
    return {ok:true, json:async () => ({rows:[row("latest", "user")], next_cursor:"older"})};
  };
  try {
    mounted = extension.surfaces[0].mount(root, {locale:"zh-CN", signal:new AbortController().signal});
    await settle();
    const button = nodes(root).find(n => n.textContent === "Markdown＋图片 ZIP");
    button.click(); await settle();
    assert.equal(exports, 1);
    assert.equal(await (await saved.fetch(anchors[0].href)).text(), "zip content");
    assert(nodes(root).some(n => n.textContent.includes("1 项提示")));
    fail = true; button.click(); await settle();
    assert(nodes(root).some(n => n.textContent.includes("对话无权访问")));
    assert.equal(anchors.length, 1);
    assert.equal(button.disabled, false);
    mounted.dispose(); mounted = null;
    await assert.rejects(saved.fetch(anchors[0].href));
  } finally {mounted?.dispose(); Object.assign(globalThis, saved);}
});

test("upload cards load lazily with credentials, open a preview and release blob URLs", async () => {
  const saved = {document:globalThis.document, window:globalThis.window, fetch:globalThis.fetch};
  const root = new Node();
  let mounted, imageCalls = 0;
  globalThis.document = {createElement:tag => Object.assign(new Node(), {tag})};
  globalThis.window = {location:{search:"?thread_id=owner-thread"}};
  globalThis.fetch = async (url, options) => {
    if (url.pathname.includes("/artifacts/")) {
      imageCalls++;
      assert.equal(options.credentials, "include");
      return new Response(new Uint8Array([1, 2, 3]), {headers:{"content-type":"image/png"}});
    }
    return {ok:true, json:async () => ({rows:[row("u", "user", {text:"<current_uploads>raw</current_uploads>", display_text:"", images:[{name:"a.png", path:"/mnt/user-data/uploads/a.png", size:"1 KB"}]})], next_cursor:null})};
  };
  try {
    mounted = extension.surfaces[0].mount(root, {locale:"zh-CN", signal:new AbortController().signal});
    await settle();
    assert.equal(imageCalls, 0);
    const card = nodes(root).find(n => n.className === "trajectory-image-card");
    card.click(); await settle();
    const dialog = nodes(root).find(n => n.tag === "dialog");
    assert.equal(dialog.open, true);
    const src = dialog.children.find(n => n.tag === "img").src;
    assert(src.startsWith("blob:"));
    card.click(); await settle(); assert.equal(imageCalls, 1);
    mounted.dispose(); mounted = null;
    await assert.rejects(saved.fetch(src));
  } finally {mounted?.dispose(); Object.assign(globalThis, saved);}
});

test("child histories load with their visible delegation and cannot update a disposed page", async () => {
  const saved = {document:globalThis.document, window:globalThis.window, fetch:globalThis.fetch};
  globalThis.document = {createElement:() => new Node()};
  globalThis.window = {location:{search:"?thread_id=child-owner"}};
  let requests = 0, finish;
  globalThis.fetch = async (url, options) => {
    assert.equal(options.credentials, "include");
    if (url.pathname.endsWith("/subagents")) {
      requests++;
      return {ok:true,json:async () => ({children:[{name:"bash",execution_id:"child-1",cursor:"child-token"}],warnings:[]})};
    }
    if (url.pathname.endsWith("/subagent-checkpoints")) {
      requests++;
      return new Promise(resolve => {finish = () => resolve({ok:true,json:async () => ({rows:[row("internal-result", "tool")],scanned:1,next_cursor:null,warnings:[]})});});
    }
    return {ok:true,json:async () => ({rows:[row("u", "user"),row("delegate", "assistant",{tool_calls:[{name:"task",id:"outer",args:"{}",subagent_cursor:"invocation"}]})],next_cursor:null,warnings:[]})};
  };
  const root = new Node();
  const mounted = extension.surfaces[0].mount(root,{locale:"zh-CN",signal:new AbortController().signal});
  try {
    await settle();
    assert.equal(requests,2);
    assert.equal(nodes(root).filter(node => node.className === "trajectory-subagents").length,0);
    mounted.dispose();
    finish(); await settle();
    assert.equal(root.children.length,0);
  } finally {mounted.dispose(); Object.assign(globalThis,saved);}
});

test("refresh ignores a late child response from the previous generation", async () => {
  const saved = {document:globalThis.document, window:globalThis.window, fetch:globalThis.fetch};
  globalThis.document = {createElement:() => new Node()};
  globalThis.window = {location:{search:"?thread_id=child-owner"}};
  let refreshed = false, finish;
  globalThis.fetch = async url => {
    if (url.pathname.endsWith("/subagents")) return {ok:true,json:async () => ({children:[{name:"bash",execution_id:refreshed ? "new" : "old",cursor:refreshed ? "new-child" : "old-child"}],warnings:[]})};
    if (url.pathname.endsWith("/subagent-checkpoints")) {
      if (url.searchParams.get("cursor") === "old-child") return new Promise(resolve => {finish = () => resolve({ok:true,json:async () => ({rows:[row("old-result")],next_cursor:null,warnings:[]})});});
      return {ok:true,json:async () => ({rows:[row("new-result")],next_cursor:null,warnings:[]})};
    }
    return {ok:true,json:async () => ({rows:[row("u","user"),row("delegate","assistant",{tool_calls:[{name:"task",id:"outer",args:"{}",subagent_cursor:refreshed ? "new-invocation" : "old-invocation"}]})],next_cursor:null,warnings:[]})};
  };
  const root = new Node();
  const mounted = extension.surfaces[0].mount(root,{locale:"zh-CN",signal:new AbortController().signal});
  try {
    await settle();
    assert.equal(typeof finish,"function");
    refreshed = true;
    nodes(root).find(node => node.textContent === "最新一轮").click();
    await settle();
    assert(nodes(root).some(node => node.textContent === "new-result"));
    finish(); await settle();
    assert(!nodes(root).some(node => node.textContent === "old-result"));
  } finally {mounted.dispose(); Object.assign(globalThis,saved);}
});

test("outer child steps share pagination and have a retryable read failure", async () => {
  const saved = {document:globalThis.document, window:globalThis.window, fetch:globalThis.fetch};
  globalThis.document = {createElement:() => new Node()};
  globalThis.window = {location:{search:"?thread_id=child-owner"}};
  let fail = true;
  globalThis.fetch = async url => {
    if (url.pathname.endsWith("/subagents")) return {ok:true,json:async () => ({children:[{name:"bash",execution_id:"E1",cursor:"child"}],warnings:[]})};
    if (url.pathname.endsWith("/subagent-checkpoints")) {
      if (fail) {fail=false; throw new Error("temporary failure");}
      return {ok:true,json:async () => ({rows:Array.from({length:205},(_,i) => row(`child-${i}`)),next_cursor:null,warnings:[]})};
    }
    return {ok:true,json:async () => ({rows:[row("u","user"),row("delegate","assistant",{tool_calls:[{name:"task",id:"outer",args:"{}",subagent_cursor:"invocation"}]})],next_cursor:null,warnings:[]})};
  };
  const root = new Node();
  const mounted = extension.surfaces[0].mount(root,{locale:"zh-CN",signal:new AbortController().signal});
  try {
    await settle();
    assert(nodes(root).some(node => node.textContent.includes("temporary failure")));
    nodes(root).find(node => node.textContent === "重试读取子轨迹").click(); await settle();
    assert(nodes(root).some(node => node.textContent === "第 1 / 3 页"));
    assert(nodes(root).filter(node => node.className === "trajectory-preview").length <= 100);
    const pagination = nodes(root).find(node => node.className === "trajectory-pagination");
    const timeline = nodes(root).find(node => node.className === "trajectory-turn").parent;
    assert.equal(pagination.parent, timeline.parent);
    assert(pagination.parent.children.indexOf(pagination) > pagination.parent.children.indexOf(timeline));
    nodes(root).find(node => node.textContent === "下一页").click();
    assert(nodes(root).some(node => node.textContent === "第 2 / 3 页"));
    assert(nodes(root).some(node => node.textContent === "child-100"));
  } finally {mounted.dispose(); Object.assign(globalThis,saved);}
});

test("automatic discovery limits concurrent child requests", async () => {
  const saved = {document:globalThis.document, window:globalThis.window, fetch:globalThis.fetch};
  globalThis.document = {createElement:() => new Node()};
  globalThis.window = {location:{search:"?thread_id=child-owner"}};
  const pending = [];
  let active = 0, maximum = 0;
  globalThis.fetch = async url => {
    if (url.pathname.endsWith("/subagents")) {
      active++; maximum = Math.max(maximum,active);
      return new Promise(resolve => {pending.push(() => {active--; resolve({ok:true,json:async () => ({children:[],warnings:[]})});});});
    }
    return {ok:true,json:async () => ({rows:[row("u","user"),row("delegate","assistant",{tool_calls:Array.from({length:3},(_,i) => ({name:"task",id:`call-${i}`,args:"{}",subagent_cursor:`invocation-${i}`}))})],next_cursor:null,warnings:[]})};
  };
  const root = new Node();
  const mounted = extension.surfaces[0].mount(root,{locale:"zh-CN",signal:new AbortController().signal});
  try {
    await settle();
    assert.equal(pending.length,2);
    pending.shift()(); await settle();
    assert.equal(pending.length,2);
    for (const release of pending.splice(0)) release();
    await settle();
    assert.equal(active,0);
    assert.equal(maximum,2);
  } finally {for (const release of pending) release(); mounted.dispose(); Object.assign(globalThis,saved);}
});

test("duration labels mark invalid or missing measurements as unrecorded", () => {
  for (const invalid of [undefined, null, {duration_ms:-1}, {duration_ms:NaN}, {duration_ms:"1"}]) {
    assert.equal(durationLabel(invalid), "未记录");
  }
  assert.equal(durationLabel({duration_ms:1250}), "1.25 s");
});

test("browser and exported facts agree on overlaps, reused IDs, collisions and parallel scopes", async () => {
  const cases=JSON.parse(await readFile(new URL("./analysis_cases.json",import.meta.url),"utf8"));
  for (const sample of cases) {
    const rows=analyzeRows(sample.rows,"thread");
    assert.deepEqual(rows.map(row=>row.row_id),sample.order,sample.name);
    const byId=new Map(rows.map(row=>[row.row_id,row]));
    for (const { row, index = 0, ...expected } of sample.calls || []) {
      const fact=byId.get(row).tool_calls[index].analysis;
      for (const [key,value] of Object.entries(expected)) assert.deepEqual(fact[key],value,`${sample.name}: ${key}`);
    }
    for (const { row, ...expected } of sample.results || []) {
      const fact=byId.get(row).analysis;
      for (const [key,value] of Object.entries(expected)) assert.deepEqual(fact[key],value,`${sample.name}: ${key}`);
    }
  }
});

test("tool failure and retry panel locates untimed attempts across pages",async()=>{
  const saved={document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch};
  globalThis.document={createElement:()=>new Node()};
  globalThis.window={location:{search:"?thread_id=retry-thread"}};
  const root=new Node();let mounted;
  const call={id:"reused",name:"read_file",args:"{}",args_fingerprint:"same",operation_targets:["/tmp/missing"]};
  globalThis.fetch=async()=>({ok:true,json:async()=>({rows:[row("u","user"),row("first","assistant",{tool_calls:[call]}),row("failure","tool",{tool_call_id:"reused",tool_status:"error"}),...Array.from({length:140},(_,i)=>row("padding-"+i)),row("retry","assistant",{tool_calls:[call]}),row("success","tool",{tool_call_id:"reused",tool_status:"success"})],next_cursor:null,warnings:[]})});
  try{
    mounted=extension.surfaces[0].mount(root,{locale:"zh-CN",signal:new AbortController().signal});await settle();
    const panel=nodes(root).find(node=>node.className==="trajectory-tools-panel");
    assert(nodes(panel).some(node=>node.className==="trajectory-panel-stats" && node.textContent==="1 项失败 · 1 项重试线索"));
    await nodes(panel).find(node=>node.textContent.includes("定位：read_file · 失败后相同调用")).click();await settle();
    assert(nodes(root).some(node=>node.className?.includes("trajectory-located") && node.attributes["data-row-id"]==="retry"));
    const currentPanel=nodes(root).find(node=>node.className==="trajectory-tools-panel");
    await nodes(currentPanel).find(node=>node.textContent.startsWith("定位：read_file · 失败 ·")).click();await settle();
    assert(nodes(root).some(node=>node.className?.includes("trajectory-located") && node.attributes["data-row-id"]==="failure"));
  }finally{mounted?.dispose();Object.assign(globalThis,saved);}
});
