import assert from "node:assert/strict";
import test from "node:test";

const {
  buildDesktopConfigSnapshot,
  removeDesktopProvider,
  saveDesktopProvider,
  deleteDesktopProvider,
  upsertDesktopProvider,
} = await import("../dist/main/config-service.js");

void test("buildDesktopConfigSnapshot returns one unified payload for the renderer", () => {
  const snapshot = buildDesktopConfigSnapshot(
    {
      defaultModel: null,
      providers: [
        {
          id: "volcengine",
          providerType: "volcengine",
          label: "Volcengine (Doubao)",
          apiKeyEnv: "VOLCENGINE_API_KEY",
          baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
          defaultModel: "doubao-seed-1-8-251228",
        },
      ],
    },
    { VOLCENGINE_API_KEY: true },
    ["doubao-seed-1-8-251228"],
  );

  assert.deepEqual(snapshot, {
    defaultModel: null,
    providers: [
      {
        id: "volcengine",
        providerType: "volcengine",
        label: "Volcengine (Doubao)",
        apiKeyEnv: "VOLCENGINE_API_KEY",
        baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
        defaultModel: "doubao-seed-1-8-251228",
      },
    ],
    secretStatuses: { VOLCENGINE_API_KEY: true },
    effectiveModels: ["doubao-seed-1-8-251228"],
  });
});

void test("upsertDesktopProvider replaces existing providers by id", () => {
  const result = upsertDesktopProvider(
    {
      defaultModel: null,
      providers: [
        {
          id: "volcengine",
          providerType: "volcengine",
          label: "Volcengine (Doubao)",
          apiKeyEnv: "VOLCENGINE_API_KEY",
          baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
          defaultModel: "doubao-seed-1-8-251228",
        },
      ],
    },
    {
      id: "volcengine",
      providerType: "volcengine",
      label: "Doubao",
      apiKeyEnv: "VOLCENGINE_API_KEY",
      baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
      defaultModel: "doubao-2",
    },
  );

  assert.deepEqual(result.providers, [
    {
      id: "volcengine",
      providerType: "volcengine",
      label: "Doubao",
      apiKeyEnv: "VOLCENGINE_API_KEY",
      baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
      defaultModel: "doubao-2",
    },
  ]);
});

void test("removeDesktopProvider returns updated settings and removed provider", () => {
  const { nextSettings, removedProvider } = removeDesktopProvider(
    {
      defaultModel: null,
      providers: [
        {
          id: "volcengine",
          providerType: "volcengine",
          label: "Volcengine (Doubao)",
          apiKeyEnv: "VOLCENGINE_API_KEY",
          baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
          defaultModel: "doubao-seed-1-8-251228",
        },
      ],
    },
    "volcengine",
  );

  assert.equal(removedProvider?.apiKeyEnv, "VOLCENGINE_API_KEY");
  assert.deepEqual(nextSettings.providers, []);
});

void test("saveDesktopProvider rolls back settings when secret persistence fails", async () => {
  const calls = [];
  const current = {
    defaultModel: null,
    providers: [],
  };
  const provider = {
    id: "openai",
    providerType: "openai",
    label: "OpenAI",
    apiKeyEnv: "OPENAI_API_KEY",
    baseUrl: "",
    defaultModel: "gpt-4o",
  };

  await assert.rejects(
    () =>
      saveDesktopProvider({
        current,
        input: { provider, apiKey: "sk-test" },
        setSettings: async (settings) => {
          calls.push(["set", settings]);
        },
        saveSecret: async () => {
          calls.push(["saveSecret"]);
          throw new Error("secret write failed");
        },
        deleteSecret: async () => {
          calls.push(["deleteSecret"]);
        },
        syncConfig: async () => {
          calls.push(["sync"]);
        },
      }),
    /secret write failed/,
  );

  assert.deepEqual(calls, [
    [
      "set",
      {
        defaultModel: null,
        providers: [provider],
      },
    ],
    ["saveSecret"],
    ["set", current],
  ]);
});

void test("saveDesktopProvider rejects apiKeyEnv changes for an existing provider", async () => {
  const current = {
    defaultModel: null,
    providers: [
      {
        id: "openai-compatible-1",
        providerType: "openai-compatible",
        label: "Custom",
        apiKeyEnv: "CUSTOM_OPENAI_COMPATIBLE_1_API_KEY",
        baseUrl: "https://example.com/v1",
        defaultModel: "model-a",
      },
    ],
  };

  await assert.rejects(
    () =>
      saveDesktopProvider({
        current,
        input: {
          provider: {
            ...current.providers[0],
            apiKeyEnv: "CUSTOM_RENAMED_API_KEY",
          },
        },
        setSettings: async () => {},
        saveSecret: async () => {},
        deleteSecret: async () => {},
        syncConfig: async () => {},
      }),
    /apiKeyEnv/,
  );
});

void test("deleteDesktopProvider restores settings when secret deletion fails", async () => {
  const calls = [];
  const current = {
    defaultModel: null,
    providers: [
      {
        id: "openai",
        providerType: "openai",
        label: "OpenAI",
        apiKeyEnv: "OPENAI_API_KEY",
        baseUrl: "",
        defaultModel: "gpt-4o",
      },
    ],
  };

  await assert.rejects(
    () =>
      deleteDesktopProvider({
        current,
        providerId: "openai",
        setSettings: async (settings) => {
          calls.push(["set", settings]);
        },
        deleteSecret: async () => {
          calls.push(["deleteSecret"]);
          throw new Error("secret delete failed");
        },
        syncConfig: async () => {
          calls.push(["sync"]);
        },
      }),
    /secret delete failed/,
  );

  assert.deepEqual(calls, [
    [
      "set",
      {
        defaultModel: null,
        providers: [],
      },
    ],
    ["deleteSecret"],
    ["set", current],
  ]);
});
