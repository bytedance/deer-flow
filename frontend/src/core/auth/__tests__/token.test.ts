import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearAccessToken, getAccessToken, isTokenExpired, setAccessToken } from "../token";

/**
 * Encode a JWT payload for testing (no real signature needed).
 */
function makeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `${header}.${body}.fake-signature`;
}

describe("token", () => {
  beforeEach(() => {
    localStorage.clear();
    clearAccessToken();
  });

  afterEach(() => {
    localStorage.clear();
    clearAccessToken();
  });

  describe("getAccessToken", () => {
    it("returns null when no token stored", () => {
      expect(getAccessToken()).toBeNull();
    });

    it("returns token from localStorage", () => {
      // Set directly in localStorage (no memory token set in this test)
      localStorage.setItem("thinktank.access_token", "stored-token");
      // Memory token is already null from beforeEach clearAccessToken()
      // so getAccessToken should fall through to localStorage
      expect(getAccessToken()).toBe("stored-token");
    });

    it("prefers memory token over localStorage", () => {
      localStorage.setItem("thinktank.access_token", "ls-token");
      setAccessToken("memory-token");
      expect(getAccessToken()).toBe("memory-token");
    });
  });

  describe("setAccessToken", () => {
    it("stores in both memory and localStorage", () => {
      setAccessToken("my-token");
      expect(getAccessToken()).toBe("my-token");
      expect(localStorage.getItem("thinktank.access_token")).toBe("my-token");
    });
  });

  describe("clearAccessToken", () => {
    it("clears from memory and localStorage", () => {
      setAccessToken("my-token");
      clearAccessToken();
      expect(getAccessToken()).toBeNull();
      expect(localStorage.getItem("thinktank.access_token")).toBeNull();
    });
  });

  describe("isTokenExpired", () => {
    it("returns true for expired token", () => {
      const past = Math.floor(Date.now() / 1000) - 3600; // 1 hour ago
      const token = makeJwt({ exp: past });
      expect(isTokenExpired(token)).toBe(true);
    });

    it("returns true for token expiring within margin", () => {
      const soon = Math.floor(Date.now() / 1000) + 60; // 60s from now (within 120s margin)
      const token = makeJwt({ exp: soon });
      expect(isTokenExpired(token, 120)).toBe(true);
    });

    it("returns false for valid token outside margin", () => {
      const future = Math.floor(Date.now() / 1000) + 3600; // 1 hour from now
      const token = makeJwt({ exp: future });
      expect(isTokenExpired(token)).toBe(false);
    });

    it("returns true for malformed token", () => {
      expect(isTokenExpired("not-a-jwt")).toBe(true);
    });

    it("returns true for token with no exp claim", () => {
      const token = makeJwt({ sub: "user-1" });
      expect(isTokenExpired(token)).toBe(true);
    });

    it("respects custom margin parameter", () => {
      const exp = Math.floor(Date.now() / 1000) + 30; // 30s from now
      const token = makeJwt({ exp });
      expect(isTokenExpired(token, 10)).toBe(false); // 30s > 10s margin
      expect(isTokenExpired(token, 60)).toBe(true); // 30s < 60s margin
    });
  });

  describe("token round-trip", () => {
    it("set -> get -> clear lifecycle", () => {
      expect(getAccessToken()).toBeNull();
      setAccessToken("lifecycle-token");
      expect(getAccessToken()).toBe("lifecycle-token");
      clearAccessToken();
      expect(getAccessToken()).toBeNull();
    });
  });
});
