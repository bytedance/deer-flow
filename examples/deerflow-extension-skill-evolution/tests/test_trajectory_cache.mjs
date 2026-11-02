import assert from "node:assert/strict";
import test from "node:test";
import { TrajectoryCache } from "../deerflow_extension_skill_evolution/static/trajectory-cache.mjs";

const tick = () => new Promise((resolve) => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test("background warmup is bounded and a click shares the same request", async () => {
  const pending = new Map();
  const calls = [];
  let running = 0, peak = 0;
  const cache = new TrajectoryCache({ load: async (name) => {
    calls.push(name);
    running += 1;
    peak = Math.max(peak, running);
    const task = deferred();
    pending.set(name, task);
    const value = await task.promise;
    running -= 1;
    return value;
  } });
  cache.warm(["a", "b", "c"]);
  await tick();
  assert.deepEqual(calls, ["a", "b"]);
  const clicked = cache.load("a", { priority: true });
  const data = { trajectories: [{ run_id: "ready" }] };
  pending.get("a").resolve(data);
  assert.equal(await clicked, data);
  await tick();
  assert.deepEqual(calls, ["a", "b", "c"]);
  pending.get("b").resolve({ trajectories: [] });
  pending.get("c").resolve({ trajectories: [] });
  await tick();
  assert.equal(peak, 2);
  assert.equal(cache.get("a").data, data);
  assert.equal(await cache.load("a"), data);
  assert.equal(calls.filter((name) => name === "a").length, 1);
});

test("expired data stays visible while it revalidates", async () => {
  let now = 0;
  const fresh = deferred();
  let calls = 0;
  const cache = new TrajectoryCache({ now: () => now, ttlMs: 100, load: async () => ++calls === 1 ? { trajectories: ["old"] } : fresh.promise });
  await cache.load("a");
  now = 101;
  const reload = cache.load("a");
  assert.deepEqual(cache.get("a").data.trajectories, ["old"]);
  assert.equal(cache.get("a").loading, true);
  fresh.resolve({ trajectories: ["new"] });
  await reload;
  assert.deepEqual(cache.get("a").data.trajectories, ["new"]);
});

test("annotation reload supersedes an older warmup response", async () => {
  const tasks = [];
  const cache = new TrajectoryCache({ load: () => {
    const task = deferred(); tasks.push(task); return task.promise;
  } });
  const oldRequest = cache.load("a");
  await tick();
  const newRequest = cache.load("a", { force: true, priority: true });
  await tick();
  tasks[1].resolve({ trajectories: ["new-annotation"] });
  await newRequest;
  tasks[0].resolve({ trajectories: ["obsolete"] });
  await oldRequest;
  assert.deepEqual(cache.get("a").data.trajectories, ["new-annotation"]);
});

test("disposal prevents queued requests and late updates", async () => {
  const controller = new AbortController();
  const active = deferred();
  const calls = [], changes = [];
  const cache = new TrajectoryCache({ concurrency: 1, signal: controller.signal, load: (name) => { calls.push(name); return active.promise; }, onChange: (name) => changes.push(name) });
  cache.warm(["a", "b"]);
  await tick();
  controller.abort();
  const afterAbort = changes.length;
  active.resolve({ trajectories: ["secret"] });
  await tick();
  assert.deepEqual(calls, ["a"]);
  assert.equal(changes.length, afterAbort);
  assert.equal(cache.get("a"), undefined);
  assert.equal(await cache.load("b"), null);
});

test("failed preloads are quiet and retry after a short cooldown", async () => {
  let now = 0, calls = 0;
  const cache = new TrajectoryCache({ now: () => now, errorTtlMs: 10, load: async () => {
    if (++calls === 1) throw new Error("UNAVAILABLE");
    return { trajectories: [] };
  } });
  await cache.load("a");
  assert.equal(cache.get("a").error, "UNAVAILABLE");
  await cache.load("a");
  assert.equal(calls, 1);
  now = 11;
  await cache.load("a");
  assert.equal(cache.get("a").error, null);
  assert.deepEqual(cache.get("a").data.trajectories, []);
});

test("page changes prune speculative queue and prioritize clicked skills", async () => {
  const tasks = new Map(), calls = [];
  const cache = new TrajectoryCache({ concurrency: 1, load: (name) => { calls.push(name); const task = deferred(); tasks.set(name, task); return task.promise; } });
  cache.warm(["old-visible", "old-next"]);
  await tick();
  cache.warm(["new-visible", "new-next"]);
  const clicked = cache.load("new-next", { priority: true });
  tasks.get("old-visible").resolve({ trajectories: [] });
  await tick();
  assert.deepEqual(calls, ["old-visible", "new-next"]);
  tasks.get("new-next").resolve({ trajectories: [] });
  await clicked;
  await tick();
  tasks.get("new-visible").resolve({ trajectories: [] });
  await tick();
  assert.equal(calls.includes("old-next"), false);
});

test("refresh invalidates in-flight results and caches are local to each page", async () => {
  const pending = deferred();
  const first = new TrajectoryCache({ load: () => pending.promise });
  const second = new TrajectoryCache({ load: async () => ({ trajectories: ["other-user"] }) });
  const old = first.load("same-skill");
  await tick();
  first.clear();
  await second.load("same-skill");
  pending.resolve({ trajectories: ["old-user"] });
  await old;
  assert.equal(first.get("same-skill"), undefined);
  assert.deepEqual(second.get("same-skill").data.trajectories, ["other-user"]);
});

test("completed entries are evicted by recency and empty results remain cached", async () => {
  const calls = [];
  const cache = new TrajectoryCache({ maxEntries: 2, load: async (name) => { calls.push(name); return { trajectories: [] }; } });
  await cache.load("a");
  await cache.load("b");
  cache.get("a");
  await cache.load("c");
  assert.equal(cache.get("b"), undefined);
  assert.deepEqual(cache.get("a").data.trajectories, []);
  await cache.load("a");
  assert.equal(calls.filter((name) => name === "a").length, 1);
});

test("permission errors drop previously cached content", async () => {
  let calls = 0;
  const cache = new TrajectoryCache({ load: async () => {
    if (++calls > 1) throw new Error("FORBIDDEN");
    return { trajectories: ["old-content"] };
  } });
  await cache.load("a");
  await cache.load("a", { force: true });
  assert.equal(cache.get("a").data, null);
  assert.equal(cache.get("a").error, "FORBIDDEN");
});
