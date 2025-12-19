import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { __internal } from "../src/core/api/admin";

const { normalizeConfig } = __internal;

describe("normalizeConfig", () => {
  it("returns empty defaults when payload is undefined", () => {
    const result = normalizeConfig(undefined);
    assert.deepStrictEqual(result, {
      tavilyApiKey: "",
      braveSearchApiKey: "",
      volcengineTtsAppId: "",
      ragflowApiKey: "",
    });
  });

  it("normalizes snake_case keys", () => {
    const result = normalizeConfig({
      tavily_api_key: "tavily",
      brave_search_api_key: "brave",
      volcengine_tts_app_id: "volc",
      ragflow_api_key: "rag",
    });

    assert.deepStrictEqual(result, {
      tavilyApiKey: "tavily",
      braveSearchApiKey: "brave",
      volcengineTtsAppId: "volc",
      ragflowApiKey: "rag",
    });
  });

  it("prefers camelCase keys when both formats are provided", () => {
    const result = normalizeConfig({
      tavilyApiKey: "camel",
      tavily_api_key: "snake",
      braveSearchApiKey: "camelBrave",
      brave_search_api_key: "snakeBrave",
    });

    assert.deepStrictEqual(result, {
      tavilyApiKey: "camel",
      braveSearchApiKey: "camelBrave",
      volcengineTtsAppId: "",
      ragflowApiKey: "",
    });
  });
});
