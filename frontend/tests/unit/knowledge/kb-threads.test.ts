/**
 * KB-thread isolation predicates (spec §5.2 库间对话隔离): threads created
 * inside the knowledge page carry ``metadata.kb_id`` — the global recent-chat
 * list excludes them, and the per-kb history popover lists exactly the
 * threads of the bound kb.
 */
import { describe, expect, test } from "@rstest/core";

import {
  excludeKnowledgeThreads,
  isKnowledgeThread,
  threadsForKb,
} from "@/core/knowledge/kb-threads";

interface FakeThread {
  thread_id: string;
  metadata?: Record<string, unknown> | null;
}

const kbThread: FakeThread = { thread_id: "t-kb", metadata: { kb_id: "kb-1", agent_name: "rag" } };
const kbThread2: FakeThread = { thread_id: "t-kb2", metadata: { kb_id: "kb-2" } };
const plainThread: FakeThread = { thread_id: "t-plain", metadata: { agent_name: "researcher" } };
const noMetaThread: FakeThread = { thread_id: "t-none", metadata: null };

describe("isKnowledgeThread", () => {
  test("true only when metadata.kb_id is a non-empty string", () => {
    expect(isKnowledgeThread(kbThread)).toBe(true);
    expect(isKnowledgeThread(kbThread2)).toBe(true);
    expect(isKnowledgeThread(plainThread)).toBe(false);
    expect(isKnowledgeThread(noMetaThread)).toBe(false);
    expect(isKnowledgeThread({ metadata: { kb_id: "" } })).toBe(false);
    expect(isKnowledgeThread({ metadata: { kb_id: 42 } })).toBe(false);
  });
});

describe("excludeKnowledgeThreads", () => {
  test("drops every kb-bound thread, keeps order of the rest", () => {
    const result = excludeKnowledgeThreads([plainThread, kbThread, noMetaThread, kbThread2]);
    expect(result.map((t) => t.thread_id)).toEqual(["t-plain", "t-none"]);
  });
});

describe("threadsForKb", () => {
  test("keeps only threads bound to the given kb", () => {
    const result = threadsForKb([kbThread, kbThread2, plainThread, noMetaThread], "kb-1");
    expect(result.map((t) => t.thread_id)).toEqual(["t-kb"]);
  });

  test("unknown kb yields an empty list", () => {
    expect(threadsForKb([kbThread], "kb-nope")).toEqual([]);
  });
});
