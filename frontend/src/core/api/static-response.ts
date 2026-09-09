import { getBackendBaseURL } from "@/core/config";
import type { FeaturesResponse } from "@/core/features/api";
import type { UserMemory } from "@/core/memory/types";

/**
 * Resolve Gateway REST calls for the read-only demo without contacting a backend.
 * Returns null for assets, mock routes, and unrelated origins so normal fetching
 * can continue. Settings reuse existing same-origin fixtures; unknown API routes
 * and writes fail locally rather than silently leaking out to a configured Gateway.
 */
export async function staticApiResponse(
  input: string,
  init?: RequestInit,
): Promise<Response | null> {
  const origin =
    typeof window === "undefined"
      ? `http://${process.env.HOSTNAME ?? "127.0.0.1"}:${process.env.PORT ?? "3000"}`
      : window.location.origin;
  const url = new URL(input, origin);
  const roots = [
    new URL(`${getBackendBaseURL()}/api/`, origin),
    new URL("/api/", origin),
  ];
  const root = roots.find(
    (candidate) =>
      url.origin === candidate.origin &&
      url.pathname.startsWith(candidate.pathname),
  );
  if (!root) return null;

  init?.signal?.throwIfAborted();
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    return Response.json(
      { detail: "Unavailable in static demo mode" },
      { status: 405 },
    );
  }

  const path = url.pathname.slice(root.pathname.length).replace(/\/$/, "");
  // These routes already own the demo settings data; do not maintain a second copy.
  if (["skills", "mcp/config", "integrations/lark/status"].includes(path)) {
    return globalThis.fetch(new URL(`/mock/api/${path}`, origin).href, init);
  }

  let data: unknown;
  switch (path) {
    case "features":
      data = {
        agents_api: { enabled: false },
        browser_control: { enabled: false },
        mcp_tasks: { enabled: false },
        subagent_batches: {
          enabled: false,
          repository_available: false,
          worker_running: false,
          max_running: 0,
        },
      } satisfies FeaturesResponse;
      break;
    case "channels/providers":
      data = { enabled: false, providers: [] };
      break;
    case "channels/connections":
      data = { connections: [] };
      break;
    case "agents":
      data = { agents: [] };
      break;
    case "subagents":
      data = { subagents: [] };
      break;
    case "suggestions/config":
      data = { enabled: false, max_suggestions: 0 };
      break;
    case "memory":
    case "memory/export": {
      const empty = { summary: "", updatedAt: "" };
      data = {
        version: "1.0",
        lastUpdated: "",
        user: { workContext: empty, personalContext: empty, topOfMind: empty },
        history: {
          recentMonths: empty,
          earlierContext: empty,
          longTermBackground: empty,
        },
        facts: [],
      } satisfies UserMemory;
      break;
    }
    default:
      // The LangGraph static client already supplies the demo transcript.
      // There is no additional durable history or live token usage to fetch.
      if (/^threads\/[^/]+\/messages\/page$/.test(path)) {
        data = { data: [], has_more: false, next_before_seq: null };
      } else if (/^threads\/[^/]+\/token-usage$/.test(path)) {
        data = null;
      } else if (
        path === "scheduled-tasks" ||
        /^scheduled-tasks\/[^/]+\/runs$/.test(path) ||
        /^threads\/[^/]+\/scheduled-tasks$/.test(path) ||
        /^threads\/[^/]+\/runs\/[^/]+\/events$/.test(path)
      ) {
        data = [];
      } else {
        return Response.json(
          { detail: "Unavailable in static demo mode" },
          { status: 404 },
        );
      }
  }
  return method === "HEAD" ? new Response(null) : Response.json(data);
}
