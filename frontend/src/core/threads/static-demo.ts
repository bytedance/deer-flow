import type { ThreadState } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";

import type { AgentThread, AgentThreadState } from "./types";

export const DEMO_THREAD_IDS = [
  "21cfea46-34bd-4aa6-9e1f-3009452fbeb9",
  "3823e443-4e2b-4679-b496-a9506eae462b",
  "4f3e55ee-f853-43db-bfb3-7d1a411f03cb",
  "5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a",
  "7cfa5f8f-a2f8-47ad-acbd-da7137baf990",
  "7f9dc56c-e49c-4671-a3d2-c492ff4dce0c",
  "90040b36-7eba-4b97-ba89-02c3ad47a8b9",
  "ad76c455-5bf9-4335-8517-fc03834ab828",
  "b83fbb2a-4e36-4d82-9de0-7b2a02c2092a",
  "c02bb4d5-4202-490e-ae8f-ff4864fc0d2e",
  "d3e5adaf-084c-4dd5-9d29-94f1d6bccd98",
  "f4125791-0128-402a-8ca9-50e0947557e4",
  "fe3f7974-1bcb-4a01-a950-79673baafefd",
] as const;

export const STATIC_DEMO_ARTIFACTS: Readonly<
  Record<string, readonly string[]>
> = {
  "21cfea46-34bd-4aa6-9e1f-3009452fbeb9": [
    "user-data/outputs/doraemon-moe-comic.jpg",
  ],
  "3823e443-4e2b-4679-b496-a9506eae462b": [
    "user-data/outputs/fei-fei-li-podcast-timeline.md",
  ],
  "4f3e55ee-f853-43db-bfb3-7d1a411f03cb": [
    "user-data/outputs/darcy-proposal-reference.jpg",
    "user-data/outputs/darcy-proposal-video.mp4",
  ],
  "5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a": [
    "user-data/outputs/jiangsu-football/css/style.css",
    "user-data/outputs/jiangsu-football/favicon.html",
    "user-data/outputs/jiangsu-football/index.html",
    "user-data/outputs/jiangsu-football/js/data.js",
    "user-data/outputs/jiangsu-football/js/main.js",
  ],
  "7cfa5f8f-a2f8-47ad-acbd-da7137baf990": [
    "user-data/outputs/index.html",
    "user-data/outputs/script.js",
    "user-data/outputs/style.css",
  ],
  "7f9dc56c-e49c-4671-a3d2-c492ff4dce0c": [
    "user-data/outputs/leica-master-photography-article.md",
    "user-data/outputs/leica-nyc-candid.jpg",
    "user-data/outputs/leica-paris-decisive-moment.jpg",
    "user-data/outputs/leica-tokyo-night.jpg",
  ],
  "90040b36-7eba-4b97-ba89-02c3ad47a8b9": [
    "user-data/outputs/american-woman-newyork.jpg",
    "user-data/outputs/american-woman-shanghai.jpg",
  ],
  "ad76c455-5bf9-4335-8517-fc03834ab828": [
    "user-data/outputs/titanic_summary.txt",
    "user-data/outputs/visualizations/class_gender_survival.png",
    "user-data/outputs/visualizations/correlation_heatmap.png",
    "user-data/outputs/visualizations/family_size_analysis.png",
    "user-data/outputs/visualizations/fare_analysis.png",
    "user-data/outputs/visualizations/survival_by_age.png",
    "user-data/outputs/visualizations/survival_by_class.png",
    "user-data/outputs/visualizations/survival_overview.png",
    "user-data/uploads/titanic.csv",
  ],
  "b83fbb2a-4e36-4d82-9de0-7b2a02c2092a": [
    "user-data/outputs/caren-hero.jpg",
    "user-data/outputs/caren-ingredients.jpg",
    "user-data/outputs/caren-lifestyle.jpg",
    "user-data/outputs/caren-products.jpg",
    "user-data/outputs/index.html",
  ],
  "c02bb4d5-4202-490e-ae8f-ff4864fc0d2e": [
    "user-data/outputs/index.html",
    "user-data/outputs/script.js",
    "user-data/outputs/styles.css",
  ],
  "d3e5adaf-084c-4dd5-9d29-94f1d6bccd98": [
    "user-data/outputs/diana_hu_research.md",
  ],
  "f4125791-0128-402a-8ca9-50e0947557e4": ["user-data/outputs/index.html"],
  "fe3f7974-1bcb-4a01-a950-79673baafefd": [
    "user-data/outputs/index.html",
    "user-data/outputs/research_deerflow_20260201.md",
  ],
};

const STATIC_DEMO_ARTIFACT_SETS = Object.fromEntries(
  Object.entries(STATIC_DEMO_ARTIFACTS).map(([threadId, artifacts]) => [
    threadId,
    new Set(artifacts),
  ]),
) as Readonly<Record<string, ReadonlySet<string>>>;

export function resolveStaticDemoArtifact(
  threadId: string,
  encodedSegments: readonly string[],
): string | null {
  const allowedArtifacts = STATIC_DEMO_ARTIFACT_SETS[threadId];
  if (!allowedArtifacts || encodedSegments[0] !== "mnt") return null;

  let segments: string[];
  try {
    segments = encodedSegments.map((segment) => decodeURIComponent(segment));
  } catch {
    return null;
  }
  if (
    segments.some(
      (segment) =>
        segment.length === 0 ||
        segment === "." ||
        segment === ".." ||
        segment.includes("/") ||
        segment.includes("\\"),
    )
  ) {
    return null;
  }

  const artifactPath = segments.slice(1).join("/");
  if (!allowedArtifacts.has(artifactPath)) return null;
  return `/demo/threads/${threadId}/${artifactPath}`;
}

const DEMO_THREAD_ID_SET = new Set<string>(DEMO_THREAD_IDS);

export function isDemoThreadId(threadId: string): boolean {
  return DEMO_THREAD_ID_SET.has(threadId);
}

export function pathOfPublicDemoThread(threadId: string): string {
  return `/showcase/${encodeURIComponent(threadId)}`;
}

export type ThreadSearchParams = NonNullable<
  Parameters<ThreadsClient["search"]>[0]
>;

export async function loadStaticDemoThreads(
  params: ThreadSearchParams = {},
): Promise<AgentThread[]> {
  const threads = await Promise.all(
    DEMO_THREAD_IDS.map((threadId) => loadStaticDemoThread(threadId)),
  );

  const sortBy = params.sortBy ?? "updated_at";
  const sortOrder = params.sortOrder ?? "desc";
  const sortedThreads = [...threads].sort((a, b) => {
    const aTimestamp = (a as unknown as Record<string, unknown>)[sortBy];
    const bTimestamp = (b as unknown as Record<string, unknown>)[sortBy];
    const aParsed = typeof aTimestamp === "string" ? Date.parse(aTimestamp) : 0;
    const bParsed = typeof bTimestamp === "string" ? Date.parse(bTimestamp) : 0;
    const aValue = Number.isNaN(aParsed) ? 0 : aParsed;
    const bValue = Number.isNaN(bParsed) ? 0 : bParsed;
    return sortOrder === "asc" ? aValue - bValue : bValue - aValue;
  });

  const offset = Math.max(0, Math.floor(params.offset ?? 0));
  const limit =
    typeof params.limit === "number"
      ? Math.max(0, Math.floor(params.limit))
      : sortedThreads.length;
  return sortedThreads.slice(offset, offset + limit);
}

export async function loadStaticDemoThread(
  threadId: string,
): Promise<AgentThread> {
  const response = await globalThis.fetch(
    `/demo/threads/${encodeURIComponent(threadId)}/thread.json`,
  );
  if (!response.ok) {
    throw new Error(`Failed to load demo thread ${threadId}`);
  }
  const thread = (await response.json()) as AgentThread;
  return {
    ...thread,
    thread_id: threadId,
    updated_at: thread.updated_at ?? thread.created_at,
  };
}

export function staticDemoThreadState(
  thread: AgentThread,
): ThreadState<AgentThreadState> {
  return {
    values: thread.values,
    next: [],
    checkpoint: {
      thread_id: thread.thread_id,
      checkpoint_ns: "",
      checkpoint_id: null,
      checkpoint_map: null,
    },
    metadata: thread.metadata ?? null,
    created_at: thread.updated_at ?? thread.created_at ?? null,
    parent_checkpoint: null,
    tasks: [],
  };
}
