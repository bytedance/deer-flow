import assert from "node:assert/strict";
import test from "node:test";

const { buildRuntimeConfigContent, getExpectedConfiguredModelNames } = await import(
  "../dist/main/runtime-config.js"
);
const { PROVIDER_PRESETS } = await import("../dist/main/config.js");

const repoConfig = `# header
log_level: info

models: []
  # Example: OpenAI model
  # - name: gpt-4
  #   display_name: GPT-4
  #   use: langchain_openai:ChatOpenAI
  #   model: gpt-4
  #   api_key: $OPENAI_API_KEY

sandbox:
  provider: local
`;

void test("replaces the entire models section with generated desktop providers", () => {
  const result = buildRuntimeConfigContent(
    repoConfig,
    [
      {
        id: "openai",
        providerType: "openai",
        label: "OpenAI",
        apiKeyEnv: "OPENAI_API_KEY",
        baseUrl: "",
        defaultModel: "gpt-4o",
      },
    ],
    PROVIDER_PRESETS,
    { OPENAI_API_KEY: "sk-test" },
  );

  assert.match(
    result,
    /models:\n  - name: "gpt-4o"\n    display_name: "OpenAI - gpt-4o"\n    use: "langchain_openai:ChatOpenAI"\n    model: "gpt-4o"\n    request_timeout: 600\n    max_retries: 2\n    api_key: "sk-test"/,
  );
  assert.doesNotMatch(result, /# Example: OpenAI model/);
  assert.match(result, /\nsandbox:\n  provider: local\n/);
});

void test("preserves an empty models list when no desktop providers are configured", () => {
  const result = buildRuntimeConfigContent(repoConfig, [], PROVIDER_PRESETS);

  assert.match(result, /\nmodels: \[\]\nsandbox:\n  provider: local\n/);
  assert.doesNotMatch(result, /# Example: OpenAI model/);
});

void test("only exposes models whose desktop providers are actually configured", () => {
  const names = getExpectedConfiguredModelNames(
    [
      {
        id: "volcengine",
        providerType: "volcengine",
        label: "Volcengine (Doubao)",
        apiKeyEnv: "VOLCENGINE_API_KEY",
        baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
        defaultModel: "doubao-seed-1-8-251228",
      },
      {
        id: "openai",
        providerType: "openai",
        label: "OpenAI",
        apiKeyEnv: "OPENAI_API_KEY",
        baseUrl: "",
        defaultModel: "gpt-4o",
      },
    ],
    PROVIDER_PRESETS,
    {
      VOLCENGINE_API_KEY: "doubao-key",
    },
  );

  assert.deepEqual(names, ["doubao-seed-1-8-251228"]);
});
