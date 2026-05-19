/**
 * Tests for the conversion-error helper.
 *
 * Covers the boundary between the backend's stable `ConversionErrorCode`
 * enum and the frontend's user-facing toast text. Adding a new code on
 * the backend must keep the toast lookup in lockstep — these tests fail
 * loudly when the table drifts.
 */
import { describe, expect, it } from "vitest";

import {
  ConversionError,
  conversionErrorToastText,
} from "@/core/uploads/conversion-errors";

describe("ConversionError class", () => {
  it("carries code, filename, and server message", () => {
    const err = new ConversionError({
      code: "ENCRYPTED_PDF",
      message: "file is password-protected",
      filename: "secret.pdf",
    });

    expect(err.name).toBe("ConversionError");
    expect(err.code).toBe("ENCRYPTED_PDF");
    expect(err.filename).toBe("secret.pdf");
    expect(err.serverMessage).toBe("file is password-protected");
    expect(err.message).toBe("file is password-protected");
  });

  it("falls back to a generic message when server omits one", () => {
    const err = new ConversionError({ code: "INTERNAL_ERROR" });
    expect(err.message).toBe("Conversion failed");
  });

  it("instanceof Error", () => {
    const err = new ConversionError({ code: "EMPTY_RESULT" });
    expect(err).toBeInstanceOf(Error);
  });
});

describe("conversionErrorToastText", () => {
  const knownCodes = [
    "EMPTY_RESULT",
    "ENCRYPTED_PDF",
    "UNSUPPORTED_FORMAT",
    "MARKITDOWN_UNAVAILABLE",
    "INTERNAL_ERROR",
  ] as const;

  it("returns a non-empty English message for every known code", () => {
    for (const code of knownCodes) {
      const txt = conversionErrorToastText(code, "en-US");
      expect(txt.length).toBeGreaterThan(10);
    }
  });

  it("returns a non-empty Chinese message for every known code", () => {
    for (const code of knownCodes) {
      const txt = conversionErrorToastText(code, "zh-CN");
      expect(txt.length).toBeGreaterThan(5);
      // Heuristic: Chinese strings should contain at least one CJK char.
      expect(/[一-鿿]/.test(txt)).toBe(true);
    }
  });

  it("prepends the filename when provided", () => {
    const txt = conversionErrorToastText(
      "ENCRYPTED_PDF",
      "en-US",
      "annual-report.pdf",
    );
    expect(txt.startsWith("annual-report.pdf:")).toBe(true);
  });

  it("falls back to a generic message for unknown codes", () => {
    const en = conversionErrorToastText(
      "BRAND_NEW_BACKEND_CODE",
      "en-US",
    );
    expect(en.toLowerCase()).toContain("conversion");

    const zh = conversionErrorToastText("BRAND_NEW_BACKEND_CODE", "zh-CN");
    expect(/[一-鿿]/.test(zh)).toBe(true);
  });

  it("Chinese and English text differ for the same code", () => {
    // Sanity: the helper actually picks a locale rather than always
    // returning the English fallback.
    expect(conversionErrorToastText("ENCRYPTED_PDF", "en-US")).not.toBe(
      conversionErrorToastText("ENCRYPTED_PDF", "zh-CN"),
    );
  });
});
