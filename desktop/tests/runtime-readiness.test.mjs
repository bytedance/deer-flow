import assert from "node:assert/strict";
import test from "node:test";

function defaultSleepFn() {
  return Promise.resolve();
}

async function importWaitForModelsApiReady() {
  const module = await import(`../dist/main/runtime-readiness.js?test=${Date.now()}`);
  return module.waitForModelsApiReady;
}

void test("waitForModelsApiReady retries until the models API returns a models array", async () => {
  const waitForModelsApiReady = await importWaitForModelsApiReady();
  const calls = [];
  let attempt = 0;

  await waitForModelsApiReady("http://127.0.0.1:3000/api/models", {
    timeoutMs: 200,
    retryDelayMs: 1,
    fetchFn: async (url) => {
      calls.push(url);
      attempt += 1;

      if (attempt < 3) {
        return {
          ok: true,
          async json() {
            return { status: "starting" };
          },
        };
      }

      return {
        ok: true,
        async json() {
          return { models: [] };
        },
      };
    },
    sleepFn: defaultSleepFn,
  });

  assert.equal(attempt, 3);
  assert.deepEqual(calls, [
    "http://127.0.0.1:3000/api/models",
    "http://127.0.0.1:3000/api/models",
    "http://127.0.0.1:3000/api/models",
  ]);
});

void test("waitForModelsApiReady times out when the models API never becomes ready", async () => {
  const waitForModelsApiReady = await importWaitForModelsApiReady();

  await assert.rejects(
    () =>
      waitForModelsApiReady("http://127.0.0.1:3000/api/models", {
        timeoutMs: 5,
        retryDelayMs: 1,
        fetchFn: async () => ({
          ok: false,
          async json() {
            return {};
          },
        }),
        sleepFn: defaultSleepFn,
      }),
    /Timed out waiting for models API readiness/,
  );
});
