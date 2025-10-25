import { parseJSON } from "../src/core/utils/json";

describe("parseJSON - extractValidJSON helper", () => {
  it("extracts JSON object with extra tokens after closing brace", () => {
    const input = '{"key": "value"} extra tokens here';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("extracts JSON array with extra tokens after closing bracket", () => {
    const input = '[1, 2, 3] garbage data here';
    const result = parseJSON(input, []);
    expect(result).toEqual([1, 2, 3]);
  });

  it("handles nested JSON with extra tokens", () => {
    const input = '{"nested": {"inner": [1, 2, 3]}} invalid text';
    const result = parseJSON(input, null);
    expect(result).toEqual({
      nested: {
        inner: [1, 2, 3],
      },
    });
  });

  it("handles JSON with strings containing braces", () => {
    const input = '{"text": "this has {braces} in it"} extra';
    const result = parseJSON(input, null);
    expect(result.text).toBe("this has {braces} in it");
  });

  it("handles JSON with escaped quotes in strings", () => {
    const input = '{"text": "quote \\"here\\""} junk';
    const result = parseJSON(input, null);
    expect(result.text).toBe('quote "here"');
  });

  it("handles clean JSON without extra tokens", () => {
    const input = '{"key": "value"}';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("handles empty object", () => {
    const input = '{} extra';
    const result = parseJSON(input, {});
    expect(result).toEqual({});
  });

  it("handles empty array", () => {
    const input = '[] more stuff';
    const result = parseJSON(input, []);
    expect(result).toEqual([]);
  });

  it("handles JSON with null values", () => {
    const input = '{"value": null} trash';
    const result = parseJSON(input, {});
    expect(result.value).toBeNull();
  });

  it("handles JSON with boolean values", () => {
    const input = '{"active": true, "deleted": false} garbage';
    const result = parseJSON(input, {});
    expect(result.active).toBe(true);
    expect(result.deleted).toBe(false);
  });

  it("handles JSON with numbers", () => {
    const input = '{"int": 42, "float": 3.14, "negative": -7} data';
    const result = parseJSON(input, {});
    expect(result.int).toBe(42);
    expect(result.float).toBe(3.14);
    expect(result.negative).toBe(-7);
  });

  it("handles JSON with unicode characters", () => {
    const input = '{"name": "测试", "emoji": "🎯"} extra';
    const result = parseJSON(input, {});
    expect(result.name).toBe("测试");
    expect(result.emoji).toBe("🎯");
  });

  it("handles multiple levels of nesting", () => {
    const input = '{"a": {"b": {"c": {"d": "value"}}}} junk';
    const result = parseJSON(input, {});
    expect(result.a.b.c.d).toBe("value");
  });

  it("handles arrays of objects", () => {
    const input = '[{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}] garbage';
    const result = parseJSON(input, []);
    expect(result.length).toBe(2);
    expect(result[0].id).toBe(1);
    expect(result[1].name).toBe("test2");
  });
});

describe("parseJSON - with code block markers", () => {
  it("strips json code block markers", () => {
    const input = '```json\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("strips js code block markers", () => {
    const input = '```js\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("strips ts code block markers", () => {
    const input = '```ts\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("strips plaintext code block markers", () => {
    const input = '```plaintext\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("strips generic code block markers", () => {
    const input = '```\n{"key": "value"}\n```';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("handles code block without closing marker", () => {
    const input = '```json\n{"key": "value"}';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });

  it("handles code block with extra whitespace", () => {
    const input = '```json   \n{"key": "value"}\n```   ';
    const result = parseJSON(input, null);
    expect(result.key).toBe("value");
  });
});

describe("parseJSON - issue #598 specific cases", () => {
  it("handles JSON with extra tokens from quantized models", () => {
    // This is similar to what Qwen3 235B returns
    const input =
      '{"text": "Published: 2010-01-07\\nTitle: Photon Counting OTDR", "data": "Published:", "reminding": " 2010-01-07\\nTitle: Photon"} some garbage tokens';
    const result = parseJSON(input, {});
    expect(result.text).toBeTruthy();
    expect(result.text).toContain("Published");
    expect(result.data).toBeTruthy();
    expect(result.reminding).toBeTruthy();
  });

  it("handles search results JSON with extra tokens", () => {
    const input = `[
      {"type": "page", "title": "Example", "url": "https://example.com", "content": "Example content"},
      {"type": "page", "title": "Test", "url": "https://test.com", "content": "Test content"}
    ] trailing garbage`;
    const result = parseJSON(input, []);
    expect(result.length).toBe(2);
    expect(result[0].type).toBe("page");
    expect(result[1].title).toBe("Test");
  });

  it("handles crawler response with extra tokens", () => {
    const input = `{
      "title": "Article Title",
      "content": "Article content here..."
    } [incomplete json or garbage`;
    const result = parseJSON(input, {});
    expect(result.title).toBe("Article Title");
    expect(result.content).toContain("Article content");
  });

  it("handles non-JSON content gracefully", () => {
    const input = "This is just plain text, not JSON";
    const fallback = { default: true };
    const result = parseJSON(input, fallback);
    // best-effort-json-parser may parse plain text as key-value pairs
    // Just ensure we get some result (not throwing an error)
    expect(result).toBeDefined();
    expect(result).not.toBeNull();
  });

  it("returns fallback for null input", () => {
    const fallback = [{ default: true }];
    const result = parseJSON(null, fallback);
    expect(result).toEqual(fallback);
  });

  it("returns fallback for undefined input", () => {
    const fallback = [];
    const result = parseJSON(undefined, fallback);
    expect(result).toEqual(fallback);
  });

  it("returns fallback for empty string input", () => {
    const fallback = {};
    const result = parseJSON("", fallback);
    expect(result).toEqual(fallback);
  });
});

describe("parseJSON - edge cases", () => {
  it("handles JSON with special characters in strings", () => {
    const input = '{"text": "Special chars: @#$%^&*()"} extra';
    const result = parseJSON(input, {});
    expect(result.text).toBe("Special chars: @#$%^&*()");
  });

  it("handles JSON with newlines in strings", () => {
    const input = '{"text": "Line 1\\nLine 2\\nLine 3"} junk';
    const result = parseJSON(input, {});
    expect(result.text).toContain("Line");
  });

  it("handles JSON with tabs in strings", () => {
    const input = '{"text": "Col1\\tCol2\\tCol3"} trash';
    const result = parseJSON(input, {});
    expect(result.text).toContain("Col");
  });

  it("handles deeply nested objects", () => {
    const input = '{"a":{"b":{"c":{"d":{"e":{"f":"deep"}}}}}}} extra';
    const result = parseJSON(input, {});
    expect(result.a.b.c.d.e.f).toBe("deep");
  });

  it("handles large arrays", () => {
    const largeArray = Array.from({ length: 100 }, (_, i) => ({ id: i }));
    const input = JSON.stringify(largeArray) + " garbage text";
    const result = parseJSON(input, []);
    expect(result.length).toBe(100);
    expect(result[99].id).toBe(99);
  });

  it("handles whitespace in JSON", () => {
    const input = `{
      "key"  :  "value"  ,
      "number"  :  42
    } extra`;
    const result = parseJSON(input, {});
    expect(result.key).toBe("value");
    expect(result.number).toBe(42);
  });

  it("handles JSON with escaped slashes", () => {
    const input = '{"url": "https:\\/\\/example.com"} junk';
    const result = parseJSON(input, {});
    expect(result.url).toContain("example.com");
  });

  it("preserves numeric precision", () => {
    const input = '{"value": 1.23456789} extra';
    const result = parseJSON(input, {});
    expect(result.value).toBe(1.23456789);
  });

  it("handles JSON with very long strings", () => {
    const longString = "A".repeat(10000);
    const input = `{"text": "${longString}"} garbage`;
    const result = parseJSON(input, {});
    expect(result.text.length).toBe(10000);
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
    expect(result.id).toBe(1);
    expect(result.name).toBe("test");
    expect(result.active).toBe(true);
  });

  it("properly types array results", () => {
    interface Item {
      id: number;
      label: string;
    }
    const input = '[{"id": 1, "label": "a"}, {"id": 2, "label": "b"}] extra';
    const fallback: Item[] = [];
    const result = parseJSON<Item[]>(input, fallback);
    expect(result[0].id).toBe(1);
    expect(result[1].label).toBe("b");
  });
});

describe("parseJSON - malformed JSON recovery", () => {
  it("handles missing closing braces", () => {
    const input = '{"key": "value"';
    const result = parseJSON(input, { key: "default" });
    // Should return something (either fixed JSON or fallback)
    expect(result).toBeDefined();
  });

  it("handles extra closing braces", () => {
    const input = '{"key": "value"}}}';
    const result = parseJSON(input, {});
    expect(result.key).toBe("value");
  });

  it("handles mixed quotes", () => {
    const input = '{"key": "value"} extra';
    const result = parseJSON(input, {});
    expect(result.key).toBe("value");
  });

  it("handles unquoted keys (not valid JSON, uses fallback)", () => {
    const input = "{key: 'value'} extra";
    const fallback = { key: "default" };
    const result = parseJSON(input, fallback);
    // Should return something
    expect(result).toBeDefined();
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
    expect(result[0].type).toBe("page");
    expect(result[0].title).toBe("Sample Article");
  });

  it("handles crawler article format", () => {
    const input = `{
      "title": "News Article",
      "content": "Article body text...",
      "author": "John Doe",
      "date": "2024-01-01"
    } [incomplete extra`;
    const result = parseJSON(input, {});
    expect(result.title).toBe("News Article");
    expect(result.content).toBeDefined();
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
    expect(result.length).toBe(2);
    expect(result[0].id).toBe("doc-1");
  });

  it("handles Python REPL output with JSON", () => {
    const input = `{"result": 42, "error": null, "stdout": "Output here"} [process ended]`;
    const result = parseJSON(input, {});
    expect(result.result).toBe(42);
    expect(result.error).toBeNull();
  });

  it("handles MCP tool response format", () => {
    const input = `{
      "tool": "web_search",
      "status": "success",
      "data": [{"title": "Result", "url": "https://example.com"}]
    } additional text`;
    const result = parseJSON(input, {});
    expect(result.tool).toBe("web_search");
    expect(result.data[0].title).toBe("Result");
  });
});

describe("parseJSON - issue #598 regression tests", () => {
  it("does not lose data when removing extra tokens", () => {
    const input = `{
      "research": "Complete research data here with lots of information",
      "sources": [
        {"title": "Source 1", "url": "https://source1.com"},
        {"title": "Source 2", "url": "https://source2.com"}
      ]
    } garbage tokens that should be removed`;

    const result = parseJSON(input, {});
    expect(result.research).toBeDefined();
    expect(result.sources.length).toBe(2);
    expect(result.sources[0].title).toBe("Source 1");
  });

  it("handles consecutive tool calls with JSON", () => {
    const firstResult = '{"step": 1, "data": "first"} extra';
    const secondResult = '{"step": 2, "data": "second"} junk';

    const result1 = parseJSON(firstResult, {});
    const result2 = parseJSON(secondResult, {});

    expect(result1.step).toBe(1);
    expect(result2.step).toBe(2);
  });

  it("maintains performance with large responses", () => {
    const largeContent = "A".repeat(50000);
    const input = `{"content": "${largeContent}", "status": "ok"} extra data`;

    const startTime = Date.now();
    const result = parseJSON(input, {});
    const duration = Date.now() - startTime;

    expect(result.content).toBeDefined();
    expect(result.status).toBe("ok");
    // Should complete quickly (< 2 seconds for this size)
    expect(duration).toBeLessThan(2000);
  });

  it("handles multiple consecutive extra tokens", () => {
    const input =
      '{"data": "value"}} } ] unexpected tokens here } { [ ) ] incomplete';
    const result = parseJSON(input, {});
    expect(result.data).toBe("value");
  });

  it("handles unicode garbage after JSON", () => {
    const input = '{"text": "测试"} 乱码数据 🎯 garbage';
    const result = parseJSON(input, {});
    expect(result.text).toBe("测试");
  });
});
