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
});
