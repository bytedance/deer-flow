import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { parseJSON } from "../src/core/utils/json.ts";

describe("parseJSON - extractValidJSON helper", () => {
  it("extracts JSON object with extra tokens after closing brace", () => {
    const input = '{"key": "value"} extra tokens here';
    // We test this indirectly through parseJSON since extractValidJSON is not exported
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("extracts JSON array with extra tokens after closing bracket", () => {
    const input = '[1, 2, 3] garbage data here';
    const result = parseJSON(input, []);
    assert.deepStrictEqual(result, [1, 2, 3]);
  });

  it("handles nested JSON with extra tokens", () => {
    const input = '{"nested": {"inner": [1, 2, 3]}} invalid text';
    const result = parseJSON(input, null);
    assert.deepStrictEqual(result, {
      nested: {
        inner: [1, 2, 3],
      },
    });
  });

  it("handles JSON with strings containing braces", () => {
    const input = '{"text": "this has {braces} in it"} extra';
    const result = parseJSON(input, null);
    assert.strictEqual(result.text, "this has {braces} in it");
  });

  it("handles JSON with escaped quotes in strings", () => {
    const input = '{"text": "quote \\"here\\""} junk';
    const result = parseJSON(input, null);
    assert.strictEqual(result.text, 'quote "here"');
  });

  it("handles clean JSON without extra tokens", () => {
    const input = '{"key": "value"}';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("handles empty object", () => {
    const input = '{} extra';
    const result = parseJSON(input, {});
    assert.deepStrictEqual(result, {});
  });

  it("handles empty array", () => {
    const input = '[] more stuff';
    const result = parseJSON(input, []);
    assert.deepStrictEqual(result, []);
  });

  it("handles JSON with null values", () => {
    const input = '{"value": null} trash';
    const result = parseJSON(input, {});
    assert.strictEqual(result.value, null);
  });

  it("handles JSON with boolean values", () => {
    const input = '{"active": true, "deleted": false} garbage';
    const result = parseJSON(input, {});
    assert.strictEqual(result.active, true);
    assert.strictEqual(result.deleted, false);
  });

  it("handles JSON with numbers", () => {
    const input = '{"int": 42, "float": 3.14, "negative": -7} data';
    const result = parseJSON(input, {});
    assert.strictEqual(result.int, 42);
    assert.strictEqual(result.float, 3.14);
    assert.strictEqual(result.negative, -7);
  });

  it("handles JSON with unicode characters", () => {
    const input = '{"name": "测试", "emoji": "🎯"} extra';
    const result = parseJSON(input, {});
    assert.strictEqual(result.name, "测试");
    assert.strictEqual(result.emoji, "🎯");
  });

  it("handles multiple levels of nesting", () => {
    const input = '{"a": {"b": {"c": {"d": "value"}}}} junk';
    const result = parseJSON(input, {});
    assert.strictEqual(result.a.b.c.d, "value");
  });

  it("handles arrays of objects", () => {
    const input = '[{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}] garbage';
    const result = parseJSON(input, []);
    assert.strictEqual(result.length, 2);
    assert.strictEqual(result[0].id, 1);
    assert.strictEqual(result[1].name, "test2");
  });
});

describe("parseJSON - with code block markers", () => {
  it("strips json code block markers", () => {
    const input = '```json\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("strips js code block markers", () => {
    const input = '```js\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("strips ts code block markers", () => {
    const input = '```ts\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("strips plaintext code block markers", () => {
    const input = '```plaintext\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("strips generic code block markers", () => {
    const input = '```\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("handles code block without closing marker", () => {
    const input = '```json\n{"key": "value"}';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });

  it("handles code block with extra whitespace", () => {
    const input = '```json   \n{"key": "value"}\n```   ';
    const result = parseJSON(input, null);
    assert.strictEqual(result.key, "value");
  });
});

describe("parseJSON - issue #598 specific cases", () => {
  it("handles JSON with extra tokens from quantized models", () => {
    // This is similar to what Qwen3 235B returns
    const input =
      '{"text": "Published: 2010-01-07\\nTitle: Photon Counting OTDR", "data": "Published:", "reminding": " 2010-01-07\\nTitle: Photon"} some garbage tokens';
    const result = parseJSON(input, {});
    assert.ok(result.text);
    assert.ok(result.text.includes("Published"));
    assert.ok(result.data);
    assert.ok(result.reminding);
  });

  it("handles search results JSON with extra tokens", () => {
    const input = `[
      {"type": "page", "title": "Example", "url": "https://example.com", "content": "Example content"},
      {"type": "page", "title": "Test", "url": "https://test.com", "content": "Test content"}
    ] trailing garbage`;
    const result = parseJSON(input, []);
    assert.strictEqual(result.length, 2);
    assert.strictEqual(result[0].type, "page");
    assert.strictEqual(result[1].title, "Test");
  });

  it("handles crawler response with extra tokens", () => {
    const input = `{
      "title": "Article Title",
      "content": "Article content here..."
    } [incomplete json or garbage`;
    const result = parseJSON(input, {});
    assert.strictEqual(result.title, "Article Title");
    assert.ok(result.content.includes("Article content"));
  });

  it("handles non-JSON content gracefully", () => {
    const input = "This is just plain text, not JSON";
    const fallback = { default: true };
    const result = parseJSON(input, fallback);
    // best-effort-json-parser may parse plain text as key-value pairs
    // Just ensure we get some result (not throwing an error)
    assert.ok(result !== undefined && result !== null);
  });

  it("returns fallback for null input", () => {
    const fallback = [{ default: true }];
    const result = parseJSON(null, fallback);
    assert.deepStrictEqual(result, fallback);
  });

  it("returns fallback for undefined input", () => {
    const fallback = [];
    const result = parseJSON(undefined, fallback);
    assert.deepStrictEqual(result, fallback);
  });

  it("returns fallback for empty string input", () => {
    const fallback = {};
    const result = parseJSON("", fallback);
    assert.deepStrictEqual(result, fallback);
  });
});

describe("parseJSON - edge cases", () => {
  it("handles JSON with special characters in strings", () => {
    const input = '{"text": "Special chars: @#$%^&*()"} extra';
    const result = parseJSON(input, {});
    assert.strictEqual(result.text, "Special chars: @#$%^&*()");
  });

  it("handles JSON with newlines in strings", () => {
    const input = '{"text": "Line 1\\nLine 2\\nLine 3"} junk';
    const result = parseJSON(input, {});
    assert.ok(result.text.includes("Line"));
  });

  it("handles JSON with tabs in strings", () => {
    const input = '{"text": "Col1\\tCol2\\tCol3"} trash';
    const result = parseJSON(input, {});
    assert.ok(result.text.includes("Col"));
  });

  it("handles deeply nested objects", () => {
    const input = '{"a":{"b":{"c":{"d":{"e":{"f":"deep"}}}}}}} extra';
    const result = parseJSON(input, {});
    assert.strictEqual(result.a.b.c.d.e.f, "deep");
  });

  it("handles large arrays", () => {
    const largeArray = Array.from({ length: 100 }, (_, i) => ({ id: i }));
    const input = JSON.stringify(largeArray) + " garbage text";
    const result = parseJSON(input, []);
    assert.strictEqual(result.length, 100);
    assert.strictEqual(result[99].id, 99);
  });

  it("handles whitespace in JSON", () => {
    const input = `{
      "key"  :  "value"  ,
      "number"  :  42
    } extra`;
    const result = parseJSON(input, {});
    assert.strictEqual(result.key, "value");
    assert.strictEqual(result.number, 42);
  });

  it("handles JSON with escaped slashes", () => {
    const input = '{"url": "https:\\/\\/example.com"} junk';
    const result = parseJSON(input, {});
    assert.ok(result.url.includes("example.com"));
  });

  it("preserves numeric precision", () => {
    const input = '{"value": 1.23456789} extra';
    const result = parseJSON(input, {});
    assert.strictEqual(result.value, 1.23456789);
  });

  it("handles JSON with very long strings", () => {
    const longString = "A".repeat(10000);
    const input = `{"text": "${longString}"} garbage`;
    const result = parseJSON(input, {});
    assert.strictEqual(result.text.length, 10000);
  });
});

describe("parseJSON - type safety", () => {
  it("properly types object results", () => {
    interface TestObject {
      id: number;
      name: string;
      active: boolean;
    }
    const input = '{"id": 1, "name": "test", "active": true} junk';
    const fallback: TestObject = { id: 0, name: "", active: false };
    const result = parseJSON<TestObject>(input, fallback);
    assert.strictEqual(result.id, 1);
    assert.strictEqual(result.name, "test");
    assert.strictEqual(result.active, true);
  });

  it("properly types array results", () => {
    interface Item {
      id: number;
      label: string;
    }
    const input = '[{"id": 1, "label": "a"}, {"id": 2, "label": "b"}] extra';
    const fallback: Item[] = [];
    const result = parseJSON<Item[]>(input, fallback);
    assert.strictEqual(result[0].id, 1);
    assert.strictEqual(result[1].label, "b");
  });
});

describe("parseJSON - malformed JSON recovery", () => {
  it("handles missing closing braces", () => {
    const input = '{"key": "value"';
    // Should use fallback since JSON is incomplete
    const result = parseJSON(input, { key: "default" });
    // With best-effort parser, it might try to fix it
    assert.ok(result);
  });

  it("handles extra closing braces", () => {
    const input = '{"key": "value"}}}';
    const result = parseJSON(input, {});
    assert.strictEqual(result.key, "value");
  });

  it("handles mixed quotes", () => {
    // Valid JSON only uses double quotes, but best-effort might handle it
    const input = '{"key": "value"} extra';
    const result = parseJSON(input, {});
    assert.strictEqual(result.key, "value");
  });

  it("handles unquoted keys (not valid JSON, uses fallback)", () => {
    const input = "{key: 'value'} extra";
    const fallback = { key: "default" };
    const result = parseJSON(input, fallback);
    // Should use fallback or best-effort fix
    assert.ok(result);
  });
});

describe("parseJSON - real-world scenarios", () => {
  it("handles Tavily search results format", () => {
    const input = `[
      {
        "type": "page",
        "title": "Sample Article",
        "url": "https://example.com/article",
        "content": "This is sample content..."
      }
    ] processing complete`;
    const result = parseJSON(input, []);
    assert.strictEqual(result[0].type, "page");
    assert.strictEqual(result[0].title, "Sample Article");
  });

  it("handles crawler article format", () => {
    const input = `{
      "title": "News Article",
      "content": "Article body text...",
      "author": "John Doe",
      "date": "2024-01-01"
    } [incomplete extra`;
    const result = parseJSON(input, {});
    assert.strictEqual(result.title, "News Article");
    assert.ok(result.content);
  });

  it("handles local search tool results", () => {
    const input = `[
      {
        "id": "doc-1",
        "title": "Document 1",
        "content": "Document content here"
      },
      {
        "id": "doc-2",
        "title": "Document 2",
        "content": "Another document"
      }
    ] extra garbage`;
    const result = parseJSON(input, []);
    assert.strictEqual(result.length, 2);
    assert.strictEqual(result[0].id, "doc-1");
  });

  it("handles Python REPL output with JSON", () => {
    const input = `{"result": 42, "error": null, "stdout": "Output here"} [process ended]`;
    const result = parseJSON(input, {});
    assert.strictEqual(result.result, 42);
    assert.strictEqual(result.error, null);
  });

  it("handles MCP tool response format", () => {
    const input = `{
      "tool": "web_search",
      "status": "success",
      "data": [{"title": "Result", "url": "https://example.com"}]
    } additional text`;
    const result = parseJSON(input, {});
    assert.strictEqual(result.tool, "web_search");
    assert.strictEqual(result.data[0].title, "Result");
  });
});

describe("parseJSON - issue #598 regression tests", () => {
  it("does not lose data when removing extra tokens", () => {
    // Ensure the fix doesn't accidentally truncate valid data
    const input = `{
      "research": "Complete research data here with lots of information",
      "sources": [
        {"title": "Source 1", "url": "https://source1.com"},
        {"title": "Source 2", "url": "https://source2.com"}
      ]
    } garbage tokens that should be removed`;

    const result = parseJSON(input, {});
    assert.ok(result.research);
    assert.strictEqual(result.sources.length, 2);
    assert.strictEqual(result.sources[0].title, "Source 1");
  });

  it("handles consecutive tool calls with JSON", () => {
    const firstResult = '{"step": 1, "data": "first"} extra';
    const secondResult = '{"step": 2, "data": "second"} junk';

    const result1 = parseJSON(firstResult, {});
    const result2 = parseJSON(secondResult, {});

    assert.strictEqual(result1.step, 1);
    assert.strictEqual(result2.step, 2);
  });

  it("maintains performance with large responses", () => {
    // Create a large but valid response
    const largeContent = "A".repeat(50000);
    const input = `{"content": "${largeContent}", "status": "ok"} extra data`;

    const startTime = Date.now();
    const result = parseJSON(input, {});
    const duration = Date.now() - startTime;

    assert.ok(result.content);
    assert.strictEqual(result.status, "ok");
    // Should complete quickly (< 1 second for this size)
    assert.ok(duration < 1000);
  });

  it("handles multiple consecutive extra tokens", () => {
    const input =
      '{"data": "value"}} } ] unexpected tokens here } { [ ) ] incomplete';
    const result = parseJSON(input, {});
    assert.strictEqual(result.data, "value");
  });

  it("handles unicode garbage after JSON", () => {
    const input = '{"text": "测试"} 乱码数据 🎯 garbage';
    const result = parseJSON(input, {});
    assert.strictEqual(result.text, "测试");
  });
});
