import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../auth/token", () => ({
  getAccessToken: vi.fn(),
}));

import { getAccessToken } from "../../auth/token";
import { DEFAULT_LOCAL_SETTINGS, getLocalSettings, saveLocalSettings } from "../local";

const mockGetAccessToken = vi.mocked(getAccessToken);

/**
 * Build a fake JWT with the given payload (no real signature).
 */
function fakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `${header}.${body}.fake-signature`;
}

describe("LocalSettings", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  // -----------------------------------------------------------------------
  // DEFAULT_LOCAL_SETTINGS
  // -----------------------------------------------------------------------
  describe("DEFAULT_LOCAL_SETTINGS", () => {
    it("has all required top-level fields", () => {
      expect(DEFAULT_LOCAL_SETTINGS).toHaveProperty("notification");
      expect(DEFAULT_LOCAL_SETTINGS).toHaveProperty("context");
      expect(DEFAULT_LOCAL_SETTINGS).toHaveProperty("models");
      expect(DEFAULT_LOCAL_SETTINGS).toHaveProperty("layout");
    });

    it("has notification enabled by default", () => {
      expect(DEFAULT_LOCAL_SETTINGS.notification.enabled).toBe(true);
    });

    it("has sidebar not collapsed by default", () => {
      expect(DEFAULT_LOCAL_SETTINGS.layout.sidebar_collapsed).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // getLocalSettings
  // -----------------------------------------------------------------------
  describe("getLocalSettings", () => {
    it("returns defaults when no token and no stored settings", () => {
      mockGetAccessToken.mockReturnValue(null);
      const result = getLocalSettings();
      expect(result).toEqual(DEFAULT_LOCAL_SETTINGS);
    });

    it("returns defaults when localStorage has no entry", () => {
      mockGetAccessToken.mockReturnValue(null);
      const result = getLocalSettings();
      expect(result.notification.enabled).toBe(true);
    });

    it("merges stored settings with defaults", () => {
      mockGetAccessToken.mockReturnValue(null);
      const stored = {
        notification: { enabled: false },
        layout: { sidebar_collapsed: true },
      };
      localStorage.setItem("thinktank.local-settings", JSON.stringify(stored));

      const result = getLocalSettings();
      expect(result.notification.enabled).toBe(false);
      expect(result.layout.sidebar_collapsed).toBe(true);
      // Defaults should fill missing fields
      expect(result.models).toBeDefined();
      expect(result.context).toBeDefined();
    });

    it("deep-merges models.providers with defaults", () => {
      mockGetAccessToken.mockReturnValue(null);
      const stored = {
        models: {
          providers: {
            openai: { enabled: true, has_key: true },
          },
        },
      };
      localStorage.setItem("thinktank.local-settings", JSON.stringify(stored));

      const result = getLocalSettings();
      // openai should be overridden
      expect(result.models.providers.openai.enabled).toBe(true);
      // Other providers should retain defaults
      expect(result.models.providers.anthropic.enabled).toBe(false);
    });

    it("handles corrupt JSON gracefully", () => {
      mockGetAccessToken.mockReturnValue(null);
      localStorage.setItem("thinktank.local-settings", "not-json{{{");

      const result = getLocalSettings();
      expect(result).toEqual(DEFAULT_LOCAL_SETTINGS);
    });
  });

  // -----------------------------------------------------------------------
  // User-scoped key via JWT
  // -----------------------------------------------------------------------
  describe("user-scoped settings key", () => {
    it("uses user-scoped key when valid JWT present", () => {
      const token = fakeJwt({ sub: "user-123" });
      mockGetAccessToken.mockReturnValue(token);

      // Save settings under user-scoped key
      const customSettings = {
        ...DEFAULT_LOCAL_SETTINGS,
        notification: { enabled: false },
      };
      saveLocalSettings(customSettings);

      // Should be stored under user-scoped key
      const storedKey = `thinktank.local-settings.user-123`;
      expect(localStorage.getItem(storedKey)).not.toBeNull();
    });

    it("falls back to base key when no token", () => {
      mockGetAccessToken.mockReturnValue(null);
      saveLocalSettings({ ...DEFAULT_LOCAL_SETTINGS, notification: { enabled: false } });
      expect(localStorage.getItem("thinktank.local-settings")).not.toBeNull();
    });

    it("falls back to base key when token has no sub", () => {
      const token = fakeJwt({ name: "no-sub" });
      mockGetAccessToken.mockReturnValue(token);
      saveLocalSettings({ ...DEFAULT_LOCAL_SETTINGS });
      expect(localStorage.getItem("thinktank.local-settings")).not.toBeNull();
    });

    it("falls back to base key when token is malformed", () => {
      mockGetAccessToken.mockReturnValue("not-a-jwt");
      saveLocalSettings({ ...DEFAULT_LOCAL_SETTINGS });
      expect(localStorage.getItem("thinktank.local-settings")).not.toBeNull();
    });

    it("isolates settings between users", () => {
      // User A saves settings
      const tokenA = fakeJwt({ sub: "user-A" });
      mockGetAccessToken.mockReturnValue(tokenA);
      saveLocalSettings({
        ...DEFAULT_LOCAL_SETTINGS,
        notification: { enabled: false },
      });

      // User B saves different settings
      const tokenB = fakeJwt({ sub: "user-B" });
      mockGetAccessToken.mockReturnValue(tokenB);
      saveLocalSettings({
        ...DEFAULT_LOCAL_SETTINGS,
        notification: { enabled: true },
      });

      // User A's settings should be unchanged
      mockGetAccessToken.mockReturnValue(tokenA);
      expect(getLocalSettings().notification.enabled).toBe(false);

      // User B's settings should be different
      mockGetAccessToken.mockReturnValue(tokenB);
      expect(getLocalSettings().notification.enabled).toBe(true);
    });
  });

  // -----------------------------------------------------------------------
  // saveLocalSettings
  // -----------------------------------------------------------------------
  describe("saveLocalSettings", () => {
    it("serializes and stores settings", () => {
      mockGetAccessToken.mockReturnValue(null);
      const settings = { ...DEFAULT_LOCAL_SETTINGS, notification: { enabled: false } };
      saveLocalSettings(settings);

      const stored = localStorage.getItem("thinktank.local-settings");
      expect(stored).not.toBeNull();
      const parsed = JSON.parse(stored!);
      expect(parsed.notification.enabled).toBe(false);
    });

    it("round-trips through save and get", () => {
      mockGetAccessToken.mockReturnValue(null);
      const settings = {
        ...DEFAULT_LOCAL_SETTINGS,
        notification: { enabled: false },
        layout: { sidebar_collapsed: true, sidebar_view_mode: "date" as const },
      };
      saveLocalSettings(settings);
      const result = getLocalSettings();
      expect(result.notification.enabled).toBe(false);
      expect(result.layout.sidebar_collapsed).toBe(true);
    });
  });
});
