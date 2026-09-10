import { describe, expect, it } from "@rstest/core";

import { parseDelimitedPreview } from "@/core/artifacts/delimited-preview";
const parse = (
  content: string,
  truncated = false,
  delimiter: "," | "\t" = ",",
) => parseDelimitedPreview({ content, truncated, delimiter });
describe("delimited preview parser", () => {
  it("preserves strings, BOM, duplicate/empty headings and quoted fields", () => {
    expect(
      parse(
        '\uFEFF名字,,名字\r\n001,"a,b","say ""hi"""\r\n12345678901234567890,"多\n行", true ',
      ).rows,
    ).toEqual([
      ["名字", "", "名字"],
      ["001", "a,b", 'say "hi"'],
      ["12345678901234567890", "多\n行", " true "],
    ]);
  });
  it.each(["\n", "\r\n", "\r"])(
    "preserves real empty records with %j",
    (newline) => {
      expect(parse(`a${newline}${newline}b${newline}`).rows).toEqual([
        ["a"],
        [""],
        ["b"],
      ]);
      expect(parse(newline).rows).toEqual([[""]]);
    },
  );
  it("distinguishes an empty file from empty fields and missing fields", () => {
    expect(parse("").rows).toEqual([]);
    expect(parse("a,b\n,\nx")).toEqual({
      rows: [["a", "b"], ["", ""], ["x"]],
      columnCount: 2,
      unevenRows: true,
      limited: false,
    });
  });
  it("uses the explicit TSV delimiter", () => {
    expect(parse('a\tb\n"x\ty"\t1,000', false, "\t").rows).toEqual([
      ["a", "b"],
      ["x\ty", "1,000"],
    ]);
  });
  it("drops only incomplete terminal prefix records", () => {
    expect(parse('a,b\n"multi\nline",tail', true).rows).toEqual([["a", "b"]]);
    expect(parse('a,b\n"multi\n', true).rows).toEqual([["a", "b"]]);
    expect(parse('a,b\n"multi\nline",tail\n', true).rows).toEqual([
      ["a", "b"],
      ["multi\nline", "tail"],
    ]);
    expect(parse("abc", true).rows).toEqual([]);
    expect(parse("\uFEFFa\nb\n", true).rows).toEqual([["a"], ["b"]]);
    expect(parse("a\n\n", true).rows).toEqual([["a"], [""]]);
  });
  it("fails malformed quote syntax even in a prefix", () => {
    expect(() => parse('a\n"unfinished')).toThrow();
    expect(() => parse('a\n"bad"x\n', true)).toThrow();
    expect(() => parse('a\n"bad"x\n')).toThrow();
  });
  it.each(["," as const, "\t" as const])(
    "ignores embedded CRs in an incomplete quoted field for delimiter %j",
    (delimiter) => {
      const prefix = `ID${delimiter}Note\r\n001${delimiter}good\r\n"hello\rworld\rthird`;
      const content = prefix + "x".repeat(1_048_576 - prefix.length);
      expect(parse(content, true, delimiter)).toEqual({
        rows: [
          ["ID", "Note"],
          ["001", "good"],
        ],
        columnCount: 2,
        limited: true,
        unevenRows: false,
      });
    },
  );
  it.each(["\r\n", "\n", "\r"])(
    "finds %j record boundaries after a quoted multiline first field",
    (newline) => {
      expect(
        parse(
          `"hello\rworld\nwith ""quotes""",Note${newline}001,good${newline}`,
        ).rows,
      ).toEqual([
        ['hello\rworld\nwith "quotes"', "Note"],
        ["001", "good"],
      ]);
    },
  );
  it("does not treat a literal quote inside an unquoted field as an opening quote", () => {
    expect(
      parse('inch",Note\r\n001,good\r\n"unfinished\ra\rb', true).rows,
    ).toEqual([
      ['inch"', "Note"],
      ["001", "good"],
    ]);
  });
  it("bounds records and fields while reporting actual sample width", () => {
    const result = parse(
      Array.from({ length: 300 }, () =>
        Array.from({ length: 60 }, (_, i) => `${i}`).join(","),
      ).join("\n"),
    );
    expect(result.rows).toHaveLength(202);
    expect(result.rows.every((row) => row.length === 50)).toBe(true);
    expect(result.columnCount).toBe(60);
    expect(result.limited).toBe(true);
    expect(result.unevenRows).toBe(false);
  });
  it("does not validate beyond the bounded record sample", () => {
    expect(parse(`${"a\n".repeat(202)}"broken`).rows).toHaveLength(202);
  });
});
