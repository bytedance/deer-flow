import { describe, expect, it } from "@rstest/core";

import {
  formatToolDetail,
  TOOL_PREVIEW_LIMIT,
} from "@/core/messages/tool-detail-preview";

describe("formatToolDetail", () => {
  it("keeps short numeric lists complete beyond the old node budget", () => {
    for (const length of [200, 1000]) {
      const values = Array.from({ length }, (_, i) => i);
      const preview = formatToolDetail(values);
      expect(preview.truncated).toBe(false);
      expect(JSON.parse(preview.text)).toEqual(values);
    }
  });
  it("visibly marks truncated lists and objects", () => {
    for (const value of [Array(20000).fill(0), { text: "x".repeat(20000) }]) {
      const preview = formatToolDetail(value);
      expect(preview.truncated).toBe(true);
      expect(preview.text).toContain("…");
      expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    }
  });
  it.each([42, { secret: "keep-me" }])(
    "preserves a real ellipsis key with value %j when object traversal is truncated",
    (original) => {
      const value: Record<string, unknown> = { "…": original };
      for (let i = 0; i < 20000; i++) value[`k${i}`] = 0;

      const preview = formatToolDetail(value);

      expect(preview.truncated).toBe(true);
      expect(
        preview.text.startsWith(
          JSON.stringify({ "…": original }, null, 2).slice(0, -2),
        ),
      ).toBe(true);
      expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    },
  );
  it("does not shorten a key into an existing ellipsis-suffixed key", () => {
    const original = { secret: "keep-me" };
    const value = {
      "k…": original,
      // Leave two characters for the next key, which used to become "k…".
      padding: "x".repeat(
        TOOL_PREVIEW_LIMIT - "k…secretkeep-mepadding".length - 2,
      ),
      keyThatMustNotBeRenamed: 0,
    };

    const preview = formatToolDetail(value);

    expect(preview.truncated).toBe(true);
    expect(
      preview.text.startsWith(
        JSON.stringify({ "k…": original }, null, 2).slice(0, -2),
      ),
    ).toBe(true);
    expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
  });
  it("omits an oversized key instead of displaying a renamed property", () => {
    const preview = formatToolDetail({
      ["k".repeat(TOOL_PREVIEW_LIMIT + 1)]: 42,
    });

    expect(preview.truncated).toBe(true);
    expect(JSON.parse(preview.text)).toEqual({ "…": "…" });
  });
  it("preserves falsy results and plain text and formats structured values", () => {
    for (const text of ["null", "false", "0", "", "plain text"]) {
      expect(formatToolDetail(text)).toEqual({ text, truncated: false });
    }
    expect(formatToolDetail({ run_id: 42 }).text).toBe('{\n  "run_id": 42\n}');
  });
  it("bounds long strings before parsing or serializing", () => {
    const result = formatToolDetail({ content: "x".repeat(1_000_000) });
    expect(result.truncated).toBe(true);
    expect(result.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    expect(formatToolDetail("x".repeat(1_000_000)).text.length).toBe(
      TOOL_PREVIEW_LIMIT,
    );
  });
  it("bounds wide and deep values without reading later getters", () => {
    const wide = Array.from({ length: 1000 }, (_, i) => i);
    Object.defineProperty(wide, "900", {
      get() {
        throw new Error("must not read");
      },
    });
    expect(formatToolDetail(wide).truncated).toBe(true);
    let deep: unknown = "leaf";
    for (let i = 0; i < 1000; i++) deep = { child: deep };
    expect(formatToolDetail(deep).truncated).toBe(true);
  });
  it("does not invoke getters or toJSON and handles cycles", () => {
    const value = {
      get secret() {
        throw new Error("must not read");
      },
      toJSON() {
        throw new Error("must not invoke");
      },
    };
    expect(formatToolDetail(value).truncated).toBe(true);
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    expect(formatToolDetail(cycle).truncated).toBe(true);
  });
  it("renders markup as plain source and limits escaped output", () => {
    expect(formatToolDetail("<script>alert(1)</script>").text).toBe(
      "<script>alert(1)</script>",
    );
    expect(
      formatToolDetail({ text: "\n".repeat(12000) }).text.length,
    ).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
  });
});

it("keeps dense previews valid JSON with complete original property names", () => {
  const value = Object.fromEntries(
    Array.from({ length: 8000 }, (_, i) => [`k${i}`, i]),
  );
  const preview = formatToolDetail(value);
  const parsed = JSON.parse(preview.text) as Record<string, unknown>;
  expect(preview.truncated).toBe(true);
  expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
  for (const [key, child] of Object.entries(parsed)) {
    if (key !== "…") expect(child).toBe(value[key]);
  }
});

it("accounts for quotes, escapes and indentation before accepting keys", () => {
  for (const key of ["L".repeat(11999), "\n".repeat(6000)]) {
    const preview = formatToolDetail({ [key]: "v".repeat(5000) });
    expect(JSON.parse(preview.text)).toEqual({ "…": "…" });
    expect(preview.truncated).toBe(true);
  }
  const preview = formatToolDetail({ nested: { text: '\n"\\'.repeat(12000) } });
  expect(() => JSON.parse(preview.text)).not.toThrow();
  expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
  expect(preview.truncated).toBe(true);
});

it("stops arrays after a child collapses even if an earlier field was truncated", () => {
  const items = Array.from({ length: 4000 }, (_, i) => ({
    i,
    deep: { a: { b: i } },
  }));
  for (const value of [
    items,
    {
      earlier: {
        get hidden() {
          throw new Error("must not read");
        },
      },
      items,
    },
  ]) {
    const preview = formatToolDetail(value);
    const parsed = JSON.parse(preview.text);
    const result = (Array.isArray(parsed) ? parsed : parsed.items) as unknown[];
    expect(preview.truncated).toBe(true);
    expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    expect(result.at(-1)).toBe("…");
    expect(result.at(-2)).not.toBe("…");
  }
});

it("preserves literal ellipsis array entries and the values after them", () => {
  expect(formatToolDetail(["…", "…", { keep: 42 }])).toEqual({
    text: JSON.stringify(["…", "…", { keep: 42 }], null, 2),
    truncated: false,
  });
});

it("coalesces generated array tail markers without changing middle positions", () => {
  const tail: unknown[] = [42];
  tail.push(tail, tail);
  const middle: unknown[] = [];
  middle.push(middle, middle, 42);
  const literal: unknown[] = [];
  literal.push(literal, "…", literal, literal);
  for (const [value, expected] of [
    [tail, [42, "…"]],
    [middle, ["…", "…", 42]],
    [literal, ["…", "…", "…"]],
    [
      [tail, middle],
      [
        [42, "…"],
        ["…", "…", 42],
      ],
    ],
  ]) {
    const preview = formatToolDetail(value);
    expect(JSON.parse(preview.text)).toEqual(expected);
    expect(preview.truncated).toBe(true);
    expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
  }
});

it("coalesces accessor, depth and budget tail markers", () => {
  const accessors = [42, 0, 0];
  for (const key of ["1", "2"]) {
    Object.defineProperty(accessors, key, {
      get() {
        throw new Error("must not read");
      },
    });
  }
  expect(JSON.parse(formatToolDetail(accessors).text)).toEqual([42, "…"]);
  let deep: unknown = [1, 2, 3];
  for (let i = 0; i < 6; i++) deep = { child: deep };
  let parsed = JSON.parse(formatToolDetail(deep).text);
  for (let i = 0; i < 6; i++) parsed = parsed.child;
  expect(parsed).toEqual(["…"]);

  const wide: unknown[] = [42];
  for (let i = 0; i < 4000; i++) wide.push(wide);
  expect(JSON.parse(formatToolDetail(wide).text)).toEqual([42, "…"]);
});

// Text is already the tool's representation; parsing it again is lossy.
it.each([
  "9223372036854775807",
  '{"run_id":9223372036854775807}',
  '[{"nested":{"run_id":-9223372036854775808}}]',
  "0.12345678901234567890123456789",
  '{"values":[1e400,1e-400,-0,9007199254740993]}',
  '{"run_id":1,"run_id":2}',
  '"quoted text"',
  '""',
  '"\\u0061\\n"',
  '  { "run_id": 42 }\n',
  "   ",
])("preserves received text verbatim: %s", (text) => {
  expect(formatToolDetail(text)).toEqual({ text, truncated: false });
});

it("keeps later array values after a cycle or inaccessible entry", () => {
  const cycle: unknown[] = [];
  cycle.push(cycle, { keep: 42 });
  expect(JSON.parse(formatToolDetail(cycle).text)).toEqual(["…", { keep: 42 }]);
  const values = [0, { keep: 42 }];
  Object.defineProperty(values, "0", {
    get() {
      throw new Error("must not read");
    },
  });
  expect(JSON.parse(formatToolDetail(values).text)).toEqual([
    "…",
    { keep: 42 },
  ]);
});

it("does not split surrogate pairs at raw or structured text limits", () => {
  for (let padding = 0; padding < 24; padding++) {
    const text = "x".repeat(padding) + "😀".repeat(12000);
    for (const value of [text, { text }, [text]]) {
      const preview = formatToolDetail(value);
      const decoded =
        typeof value === "string" ? preview.text : JSON.parse(preview.text);
      const result =
        typeof decoded === "string"
          ? decoded
          : Array.isArray(decoded)
            ? decoded[0]
            : decoded.text;
      expect(result.isWellFormed()).toBe(true);
      expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
      expect(preview.truncated).toBe(true);
    }
  }
});

it("preserves representable siblings next to a depth-limited value", () => {
  let value: unknown = [{ deep: { tooDeep: true } }, 42];
  for (let i = 0; i < 5; i++) value = { child: value };
  let parsed = JSON.parse(formatToolDetail(value).text);
  for (let i = 0; i < 5; i++) parsed = parsed.child;
  expect(parsed).toEqual([{ deep: "…" }, 42]);
});

it("checks bounded JSON and data fidelity across a deterministic mixed corpus", () => {
  let seed = 5309;
  const random = (max: number) => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed % max;
  };
  const strings = ["", "…", "key…", "__proto__", '"\\\n\t', "😀中文"];
  const generate = (depth: number): unknown => {
    switch (random(depth < 4 ? 7 : 4)) {
      case 0:
        return null;
      case 1:
        return random(2) === 1;
      case 2:
        return random(200000) - 100000;
      case 3:
        return strings[random(strings.length)]!.repeat(random(20));
      case 4:
        return Array.from({ length: random(10) }, () => generate(depth + 1));
      default:
        return Object.fromEntries(
          Array.from({ length: random(10) }, (_, i) => [
            strings[random(strings.length)]! + i,
            generate(depth + 1),
          ]),
        );
    }
  };
  const check = (original: unknown, displayed: unknown) => {
    if (displayed === "…") return;
    if (typeof original === "string" && typeof displayed === "string") {
      expect(
        displayed === original ||
          (displayed.endsWith("…") &&
            original.startsWith(displayed.slice(0, -1))),
      ).toBe(true);
    } else if (Array.isArray(original)) {
      expect(Array.isArray(displayed)).toBe(true);
      (displayed as unknown[]).forEach((child, i) => check(original[i], child));
    } else if (original !== null && typeof original === "object") {
      expect(displayed).not.toBeNull();
      for (const [key, child] of Object.entries(
        displayed as Record<string, unknown>,
      )) {
        if (key === "…" && child === "…") continue;
        expect(Object.prototype.hasOwnProperty.call(original, key)).toBe(true);
        check((original as Record<string, unknown>)[key], child);
      }
    } else expect(displayed).toEqual(original);
  };
  for (let i = 0; i < 500; i++) {
    const value = { data: generate(0) };
    const preview = formatToolDetail(value);
    expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    const parsed = JSON.parse(preview.text);
    check(value, parsed);
    if (!preview.truncated) expect(parsed).toEqual(value);
  }
});

it("keeps structure and accurate truncation flags around the text boundary", () => {
  for (
    let size = TOOL_PREVIEW_LIMIT - 100;
    size <= TOOL_PREVIEW_LIMIT + 10;
    size++
  ) {
    const raw = "x".repeat(size);
    const preview = formatToolDetail(raw);
    expect(preview.truncated).toBe(size > TOOL_PREVIEW_LIMIT);
    expect(preview.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    for (const value of [{ text: raw }, [raw], { nested: [raw] }]) {
      const structured = formatToolDetail(value);
      expect(() => JSON.parse(structured.text)).not.toThrow();
      expect(structured.text.length).toBeLessThanOrEqual(TOOL_PREVIEW_LIMIT);
    }
  }
});
