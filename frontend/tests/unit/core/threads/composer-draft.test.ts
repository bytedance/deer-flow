import { describe, expect, it } from "@rstest/core";

import {
  buildComposerDraftKey,
  clearComposerDraft,
  getSessionComposerDraftStorage,
  readComposerDraft,
  resolveComposerDraft,
  writeComposerDraft,
  type ComposerDraftStorage,
} from "@/core/threads/composer-draft";

class MemoryStorage implements ComposerDraftStorage {
  readonly values = new Map<string, string>();
  throwOnRead = false;
  throwOnWrite = false;

  getItem(key: string) {
    if (this.throwOnRead) {
      throw new DOMException("Storage is unavailable");
    }
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    if (this.throwOnWrite) {
      throw new DOMException("Storage quota exceeded");
    }
    this.values.set(key, value);
  }

  removeItem(key: string) {
    if (this.throwOnWrite) {
      throw new DOMException("Storage is unavailable");
    }
    this.values.delete(key);
  }
}

describe("composer draft storage", () => {
  it("isolates drafts by user, agent, and thread", () => {
    const base = {
      userId: "user:1",
      agentName: "lead-agent",
      threadId: "thread/1",
    };

    const key = buildComposerDraftKey(base);

    expect(key).not.toBe(buildComposerDraftKey({ ...base, userId: "user:2" }));
    expect(key).not.toBe(
      buildComposerDraftKey({ ...base, agentName: "reviewer" }),
    );
    expect(key).not.toBe(
      buildComposerDraftKey({ ...base, threadId: "thread/2" }),
    );
    expect(key).toContain("user%3A1");
    expect(key).toContain("thread%2F1");
  });

  it("round-trips text and a selected slash skill", () => {
    const storage = new MemoryStorage();
    const key = "draft-key";
    const draft = {
      text: "Summarize the uploaded report",
      skillName: "data-analysis",
    };

    writeComposerDraft(storage, key, draft);

    expect(readComposerDraft(storage, key)).toEqual(draft);
  });

  it("removes empty drafts and explicitly cleared drafts", () => {
    const storage = new MemoryStorage();
    const key = "draft-key";
    writeComposerDraft(storage, key, { text: "temporary", skillName: null });

    writeComposerDraft(storage, key, { text: "", skillName: null });
    expect(storage.values.has(key)).toBe(false);

    writeComposerDraft(storage, key, { text: "temporary", skillName: null });
    clearComposerDraft(storage, key);
    expect(storage.values.has(key)).toBe(false);
  });

  it("falls back to editable slash text when the saved skill is unavailable", () => {
    expect(
      resolveComposerDraft(
        {
          text: "Analyze the latest results",
          skillName: "data-analysis",
        },
        new Set(["data-analysis"]),
      ),
    ).toEqual({
      text: "Analyze the latest results",
      skillName: "data-analysis",
    });

    expect(
      resolveComposerDraft(
        {
          text: "Analyze the latest results",
          skillName: "data-analysis",
        },
        new Set(),
      ),
    ).toEqual({
      text: "/data-analysis Analyze the latest results",
      skillName: null,
    });
  });

  it("ignores malformed payloads and unavailable storage", () => {
    const storage = new MemoryStorage();
    storage.values.set("malformed", "{not-json");
    storage.values.set(
      "wrong-version",
      JSON.stringify({ version: 2, text: "future", skillName: null }),
    );

    expect(readComposerDraft(storage, "malformed")).toBeNull();
    expect(readComposerDraft(storage, "wrong-version")).toBeNull();

    storage.throwOnRead = true;
    expect(readComposerDraft(storage, "draft-key")).toBeNull();

    storage.throwOnRead = false;
    storage.throwOnWrite = true;
    expect(() =>
      writeComposerDraft(storage, "draft-key", {
        text: "keep typing",
        skillName: null,
      }),
    ).not.toThrow();
    expect(() => clearComposerDraft(storage, "draft-key")).not.toThrow();
  });

  it("treats missing storage as unavailable instead of throwing", () => {
    expect(readComposerDraft(null, "draft-key")).toBeNull();
    expect(() =>
      writeComposerDraft(null, "draft-key", {
        text: "keep typing",
        skillName: null,
      }),
    ).not.toThrow();
    expect(() => clearComposerDraft(null, "draft-key")).not.toThrow();
  });

  it("returns null when the browser sessionStorage getter is blocked", () => {
    const originalWindow = globalThis.window;
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: Object.defineProperty({}, "sessionStorage", {
        configurable: true,
        get() {
          throw new DOMException("Blocked", "SecurityError");
        },
      }),
    });

    try {
      expect(getSessionComposerDraftStorage()).toBeNull();
    } finally {
      Object.defineProperty(globalThis, "window", {
        configurable: true,
        value: originalWindow,
      });
    }
  });
});
