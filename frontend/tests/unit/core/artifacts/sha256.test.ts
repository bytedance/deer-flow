import { describe, expect, it } from "@rstest/core";

import { sha256Hex } from "@/core/artifacts/sha256";

function hexFromText(text: string): string {
  return sha256Hex(new TextEncoder().encode(text));
}

describe("sha256Hex", () => {
  it("matches the SHA-256 of an empty input", () => {
    expect(hexFromText("")).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });

  it("matches the SHA-256 of 'abc'", () => {
    expect(hexFromText("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("matches the SHA-256 of 'content' used by artifact revisions", () => {
    expect(hexFromText("content")).toBe(
      "ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73",
    );
  });

  it("handles inputs spanning multiple 64-byte blocks", async () => {
    const text = "a".repeat(200);
    const digest = await globalThis.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(text),
    );
    const expected = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    expect(hexFromText(text)).toBe(expected);
  });

  it("matches SHA-256 at the padding boundary (55 bytes)", () => {
    // 55-byte input: the 8-byte length field lands exactly at the block boundary,
    // the classic off-by-one spot for hand-rolled SHA-2 padding.
    expect(hexFromText("a".repeat(55))).toBe(
      "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318",
    );
  });

  it("matches SHA-256 at the padding boundary (56 bytes)", () => {
    // 56-byte input: paddedLength flips from one to two blocks.
    expect(hexFromText("a".repeat(56))).toBe(
      "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a",
    );
  });

  it("matches SHA-256 at the padding boundary (64 bytes)", () => {
    // 64-byte input: exactly one full block, padding starts a second block.
    expect(hexFromText("a".repeat(64))).toBe(
      "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb",
    );
  });
});
