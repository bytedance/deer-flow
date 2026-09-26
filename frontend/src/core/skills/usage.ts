import type { Message } from "@langchain/langgraph-sdk";

import { getMessageRunId } from "@/core/messages/run-duration";
import type { MessageGroup } from "@/core/messages/utils";

export const SKILL_USAGES_KEY = "skill_usages";

/** Display evidence captured at load time, never a catalog/authorization source. */
export interface SkillUsage {
  name: string;
  description: string;
  category: string;
  path: string;
  content: string;
  content_hash: string;
  activation: "automatic" | "slash";
  partial: boolean;
}

export function readSkillUsage(message: Message): SkillUsage | undefined {
  if (message.type !== "ai" && message.type !== "tool") return undefined;
  if (message.type === "tool" && message.status === "error") return undefined;
  return parseSkillUsage(message.additional_kwargs?.skill_usage);
}

function parseSkillUsage(raw: unknown): SkillUsage | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const value = raw as Record<string, unknown>;
  if (
    typeof value.name !== "string" ||
    !value.name ||
    typeof value.description !== "string" ||
    typeof value.category !== "string" ||
    typeof value.path !== "string" ||
    !value.path.endsWith("/SKILL.md") ||
    typeof value.content !== "string" ||
    typeof value.content_hash !== "string" ||
    !/^[a-f0-9]{64}$/.test(value.content_hash) ||
    (value.activation !== "automatic" && value.activation !== "slash") ||
    typeof value.partial !== "boolean"
  )
    return undefined;
  return value as unknown as SkillUsage;
}

/** One menu on the last assistant bubble per run, in first-load order.
 * Live messages may not yet carry run ids; use visible human and clarification
 * boundaries until history provides those ids. Never infer usage from answer
 * text or the catalog.
 */
export function getSkillUsageByGroupIndex(
  groups: MessageGroup[],
): Map<number, SkillUsage[]> {
  const byRun = new Map<
    string,
    { skills: Map<string, SkillUsage>; anchor?: number }
  >();
  let start = 0;
  while (start < groups.length) {
    let end = start + 1;
    while (
      end < groups.length &&
      groups[end]?.type !== "human" &&
      groups[end - 1]?.type !== "assistant:clarification"
    )
      end++;
    const runIds = new Set<string>();
    for (let i = start; i < end; i++) {
      for (const message of groups[i]!.messages) {
        if (message.type === "human") continue;
        const runId = getMessageRunId(message);
        if (runId) runIds.add(runId);
      }
    }
    let currentKey =
      runIds.size === 1 ? `run:${[...runIds][0]}` : `turn:${start}`;
    for (let i = start; i < end; i++) {
      const group = groups[i]!;
      for (const message of group.messages) {
        if (message.type !== "ai" && message.type !== "tool") continue;
        const runId = getMessageRunId(message);
        if (runId) currentKey = `run:${runId}`;
        let run = byRun.get(currentKey);
        if (!run) {
          run = { skills: new Map() };
          byRun.set(currentKey, run);
        }
        const aggregate: unknown =
          message.additional_kwargs?.[SKILL_USAGES_KEY];
        const usages =
          message.type === "ai" && Array.isArray(aggregate)
            ? aggregate.map(parseSkillUsage)
            : [readSkillUsage(message)];
        if (message.type === "ai" && Array.isArray(aggregate)) {
          // The aggregate preserves first-load order/content even when earlier
          // reads are absent from the currently loaded history page.
          const canonical = new Map<string, SkillUsage>();
          for (const usage of usages) {
            if (usage && !canonical.has(usage.path))
              canonical.set(usage.path, usage);
          }
          for (const [path, usage] of run.skills) {
            if (!canonical.has(path)) canonical.set(path, usage);
          }
          run.skills = canonical;
        }
        for (const usage of usages) {
          if (usage && !run.skills.has(usage.path))
            run.skills.set(usage.path, usage);
        }
        if (group.type === "assistant" && message.type === "ai") run.anchor = i;
      }
    }
    start = end;
  }
  const result = new Map<number, SkillUsage[]>();
  for (const run of byRun.values()) {
    if (run.anchor !== undefined && run.skills.size > 0)
      result.set(run.anchor, [...run.skills.values()]);
  }
  return result;
}
