import { DEMO_THREAD_IDS } from "@/core/threads/static-demo";

type ThreadSearchRequest = {
  limit?: number;
  offset?: number;
  sortBy?: "updated_at" | "created_at";
  sortOrder?: "asc" | "desc";
};

type MockThreadSearchResult = Record<string, unknown> & {
  thread_id: string;
  updated_at: string | undefined;
};

export async function POST(request: Request) {
  const body = ((await request.json().catch(() => ({}))) ??
    {}) as ThreadSearchRequest;

  const rawLimit = body.limit;
  let limit = 50;
  if (typeof rawLimit === "number") {
    const normalizedLimit = Math.max(0, Math.floor(rawLimit));
    if (!Number.isNaN(normalizedLimit)) {
      limit = normalizedLimit;
    }
  }

  const rawOffset = body.offset;
  let offset = 0;
  if (typeof rawOffset === "number") {
    const normalizedOffset = Math.max(0, Math.floor(rawOffset));
    if (!Number.isNaN(normalizedOffset)) {
      offset = normalizedOffset;
    }
  }
  const sortBy = body.sortBy ?? "updated_at";
  const sortOrder = body.sortOrder ?? "desc";

  const origin = new URL(request.url).origin;
  const threadData = (
    await Promise.all(
      DEMO_THREAD_IDS.map(
        async (threadId): Promise<MockThreadSearchResult | null> => {
          const response = await fetch(
            new URL(
              `/demo/threads/${encodeURIComponent(threadId)}/thread.json`,
              origin,
            ),
            { signal: request.signal },
          );
          if (!response.ok) return null;
          const data = (await response.json()) as Record<string, unknown>;
          const thread: MockThreadSearchResult = {
            ...data,
            thread_id: threadId,
            updated_at:
              typeof data.updated_at === "string"
                ? data.updated_at
                : typeof data.created_at === "string"
                  ? data.created_at
                  : undefined,
          };
          return thread;
        },
      ),
    )
  )
    .filter((thread): thread is MockThreadSearchResult => thread !== null)
    .sort((a, b) => {
      const aTimestamp = a[sortBy];
      const bTimestamp = b[sortBy];
      const aParsed =
        typeof aTimestamp === "string" ? Date.parse(aTimestamp) : 0;
      const bParsed =
        typeof bTimestamp === "string" ? Date.parse(bTimestamp) : 0;
      const aValue = Number.isNaN(aParsed) ? 0 : aParsed;
      const bValue = Number.isNaN(bParsed) ? 0 : bParsed;
      return sortOrder === "asc" ? aValue - bValue : bValue - aValue;
    });

  const pagedThreads = threadData.slice(offset, offset + limit);
  return Response.json(pagedThreads);
}
