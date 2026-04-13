import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/components/workspace/settings/model-settings-delete-dialog-state.js"),
).href;

async function importHelper() {
  const imported = await import(`${helperPath}?test=${Date.now()}`);
  return imported.reduceDeleteDialogState;
}

void test("closing delete dialog keeps the selected provider visible until fully closed", async () => {
  const reduceDeleteDialogState = await importHelper();
  const provider = {
    id: "openai",
    label: "OpenAI",
    apiKeyEnv: "OPENAI_API_KEY",
  };

  const next = reduceDeleteDialogState(
    {
      open: true,
      provider,
    },
    {
      type: "close",
    },
  );

  assert.deepEqual(next, {
    open: false,
    provider,
  });
});

void test("opening delete dialog stores the selected provider", async () => {
  const reduceDeleteDialogState = await importHelper();
  const provider = {
    id: "anthropic",
    label: "Anthropic",
    apiKeyEnv: "ANTHROPIC_API_KEY",
  };

  const next = reduceDeleteDialogState(
    {
      open: false,
      provider: null,
    },
    {
      type: "open",
      provider,
    },
  );

  assert.deepEqual(next, {
    open: true,
    provider,
  });
});
