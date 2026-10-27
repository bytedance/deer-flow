import assert from "node:assert/strict";
import test from "node:test";
import { createEvolutionModules } from "../deerflow_extension_skill_evolution/static/modules.mjs";

test("only available modules can instantiate a capability UI", () => {
  const calls = [];
  const context = { locale: "zh-CN" };
  const instance = { refresh() {} };
  const modules = createEvolutionModules({ skill: (ctx) => { calls.push(ctx); return instance; } });
  assert.deepEqual(calls, []);
  const skill = modules.find((module) => module.id === "skill");
  const memory = modules.find((module) => module.id === "memory");
  assert.equal(skill.create(context), instance);
  assert.deepEqual(calls, [context]);
  assert.equal(memory.state, "planned");
  assert.equal(memory.create, undefined);
  assert.equal(new Set(modules.map((module) => module.id)).size, modules.length);
});

const { stageAndCheck, orderTargetSkills } = await import("../deerflow_extension_skill_evolution/static/skill.mjs");

test("selected and unsaved skill choices sort first without losing missing targets", () => {
  assert.deepEqual(orderTargetSkills(["alpha", "zulu", "beta"], ["zulu", "missing"]), ["missing", "zulu", "alpha", "beta"]);
  assert.deepEqual(orderTargetSkills(["alpha", "zulu"], ["zulu"], new Map([["alpha", true], ["zulu", false]])), ["alpha", "zulu"]);
});

test("stage triggers a check on the exact new proposal after exposing pending state", async () => {
  const calls = [];
  const context = { callBackend: async (action, payload) => {
    calls.push([action, payload]);
    return action === "managed_stage" ? { ok: true, proposal: { proposal_id: "new-proposal" } } : { ok: true, check: { decision: "deny", reason_code: "STATIC_SCAN_REJECTED" } };
  } };
  const result = await stageAndCheck(context, { skill_name: "demo", content: "draft" }, (proposal) => calls.push(["staged", proposal.proposal_id]));
  assert.deepEqual(calls.map(([name]) => name), ["managed_stage", "staged", "managed_check"]);
  assert.deepEqual(calls[2][1], { proposal_id: "new-proposal" });
  assert.equal(result.check.decision, "deny");
});

test("failed staging never checks; failed checking leaves staged proposal recoverable", async () => {
  let staged = null;
  const calls = [];
  const context = { callBackend: async (action) => {
    calls.push(action);
    return { ok: false, error: { code: "STAGE_FAILED" } };
  } };
  await assert.rejects(stageAndCheck(context, {}, () => assert.fail("must not stage")), /STAGE_FAILED/);
  assert.deepEqual(calls, ["managed_stage"]);
  context.callBackend = async (action) => action === "managed_stage"
    ? { ok: true, proposal: { proposal_id: "retry-me" } }
    : { ok: false, error: { code: "CHECK_UNAVAILABLE" } };
  await assert.rejects(stageAndCheck(context, {}, (proposal) => { staged = proposal; }), /CHECK_UNAVAILABLE/);
  assert.equal(staged.proposal_id, "retry-me");
});

test("an aborted or malformed stage cannot start a check", async () => {
  let checks = 0;
  const context = { callBackend: async (action) => {
    if (action === "managed_check") checks += 1;
    return { ok: true, proposal: {} };
  } };
  await assert.rejects(stageAndCheck(context, {}, () => assert.fail("invalid proposal")), /INVALID_PROPOSAL/);
  context.signal = AbortSignal.abort();
  context.callBackend = async (action) => {
    if (action === "managed_check") checks += 1;
    return { ok: true, proposal: { proposal_id: "staged-but-disposed" } };
  };
  await assert.rejects(stageAndCheck(context, {}, () => assert.fail("disposed")), /ABORTED/);
  assert.equal(checks, 0);
});

const { createConfigureCard, evolutionModelChoices } = await import("../deerflow_extension_skill_evolution/static/skill.mjs");

test("model choices reuse the chat catalog without plugin role grants", () => {
  const choices = evolutionModelChoices([{ name: "GLM-5-3" }, { name: "GLM-5-2", display_name: "GLM-5.2" }]);
  assert.deepEqual(choices, [{ name: "GLM-5-3", display: "GLM-5-3" }, { name: "GLM-5-2", display: "GLM-5.2" }]);
  assert.equal(choices.some((model) => "granted" in model || "role" in model), false);
});

test("configuration request failures show an error rather than an endless loading placeholder", async () => {
  const previousDocument = globalThis.document;
  class Element {
    constructor() { this.children = []; this.textContent = ""; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
  }
  globalThis.document = { createElement: () => new Element() };
  try {
    const card = createConfigureCard({ locale: "zh", callBackend: async () => { throw new Error("CONFIG_UNAVAILABLE"); } });
    await card.refresh();
    const text = (element) => [element.textContent, ...element.children.map(text)].join(" ");
    assert.match(text(card.card), /配置加载失败.*CONFIG_UNAVAILABLE/);
    assert.doesNotMatch(text(card.card), /正在读取配置/);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});


const { trajectoryActivationPoints } = await import("../deerflow_extension_skill_evolution/static/skill.mjs");

test("activation navigation uses recorded activation flags and original journal sequence numbers", () => {
  const events = [
    { event_id: "message", seq: 2, kind: "human" },
    { event_id: "first", seq: 20, invocation: true },
    { event_id: "tool", seq: 24, kind: "tool", preview: "skill executed" },
    { event_id: "other", seq: 28, invocation: false },
    { event_id: "second", seq: 43, invocation: true },
  ];
  assert.deepEqual(trajectoryActivationPoints(events), [
    { index: 1, eventId: "first", seq: 20 },
    { index: 4, eventId: "second", seq: 43 },
  ]);
  assert.deepEqual(trajectoryActivationPoints(undefined), []);
  assert.deepEqual(trajectoryActivationPoints([]), []);
});


const { createTrajectoryRunContext } = await import("../deerflow_extension_skill_evolution/static/skill.mjs");

test("run context surfaces user input independently of activation order without reordering events", () => {
  const previousDocument = globalThis.document;
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; }
    append(...children) { this.children.push(...children); }
  }
  globalThis.document = { createElement: (tag) => new Element(tag) };
  try {
    const events = [
      { kind: "activation", seq: 20, preview: "activated" },
      { kind: "human", seq: 21, preview: "<script>user text</script>" },
      { kind: "ai", seq: 22, preview: "done" },
    ];
    const box = createTrajectoryRunContext({ locale: "zh-CN" }, { thread_id: "thread/one?x=2" }, events);
    const link = box.children[0].children[1];
    assert.equal(link.href, "/workspace/chats/thread%2Fone%3Fx%3D2");
    assert.equal(link.target, "_blank");
    assert.equal(link.rel, "noopener noreferrer");
    assert.equal(box.children[2].textContent, "<script>user text</script>");
    assert.equal(box.children[3].textContent, "来源事件 #21");
    assert.deepEqual(events.map((event) => event.seq), [20, 21, 22]);
    const missing = createTrajectoryRunContext({ locale: "zh-CN" }, {}, [{ kind: "ai", preview: "not a user message" }]);
    assert.equal(missing.children[0].children.length, 1);
    assert.equal(missing.children[2].textContent, "本次运行暂无可展示的用户输入。");
  } finally {
    globalThis.document = previousDocument;
  }
});


const { createSkillsCard } = await import("../deerflow_extension_skill_evolution/static/skill.mjs");

test("version viewing is read-only, precedes staging, and shares diffs with rollback history", async () => {
  const previousDocument = globalThis.document;
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
  }
  globalThis.document = { createElement: (tag) => new Element(tag), createTextNode: (value) => ({ textContent: value, children: [] }) };
  const abort = new AbortController();
  const calls = [];
  try {
    const context = { locale: "zh-CN", signal: abort.signal, callBackend: async (action, payload) => {
      calls.push([action, payload]);
      if (action === "evolved_skills") return { ok: true, skills: [{ name: "demo", history: [
        { seq: 2, operation_id: "new", has_content: true },
        { seq: 1, operation_id: "old", has_content: true },
      ] }] };
      if (action === "evolved_version") return { ok: true, version: { content: payload.operation_id === "new" ? "new content" : "old content" } };
      return { ok: true, trajectories: [] };
    } };
    const ui = createSkillsCard(context);
    ui.setOperations(["stage", "check", "commit", "revert"]);
    ui.setFeedbackMode("agent");
    await ui.refresh();
    const flatten = (root) => [root, ...root.children.flatMap(flatten)];
    const buttons = () => flatten(ui.card).filter((element) => element.tag === "button");
    assert.deepEqual(buttons().slice(0, 3).map((element) => element.textContent), ["查看版本", "暂存", "检查"]);
    buttons().find((element) => element.textContent === "查看版本").onclick();
    assert.equal(buttons().some((element) => ["恢复此版本", "撤销此操作"].includes(element.textContent)), false);
    assert.equal(buttons().filter((element) => element.textContent === "查看变更").length, 2);
    buttons().find((element) => element.textContent === "查看变更").onclick();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.deepEqual(calls.filter(([action]) => action === "evolved_version").map(([, payload]) => payload.operation_id), ["new", "old"]);
    assert.ok(flatten(ui.card).some((element) => element.textContent === "+ new content"));
    assert.ok(flatten(ui.card).some((element) => element.textContent === "- old content"));
    assert.equal(calls.some(([action]) => action.startsWith("managed_")), false);
    buttons().find((element) => element.textContent === "回滚").onclick();
    assert.equal(buttons().some((element) => element.textContent === "撤销此操作"), true);
    assert.equal(buttons().some((element) => element.textContent === "恢复此版本"), true);
    buttons().find((element) => element.textContent === "查看版本").onclick();
    assert.equal(buttons().some((element) => ["恢复此版本", "撤销此操作"].includes(element.textContent)), false);
  } finally {
    abort.abort();
    globalThis.document = previousDocument;
  }
});
