import fs from "fs";
import path from "path";

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
  const body = ((await request.json().catch(() => ({}))) ?? {}) as ThreadSearchRequest;
  const limit = body.limit ?? 50;
  const offset = body.offset ?? 0;
  const sortBy = body.sortBy ?? "updated_at";
  const sortOrder = body.sortOrder ?? "desc";

  const threadsDir = fs.readdirSync(
    path.resolve(process.cwd(), "public/demo/threads"),
    {
      withFileTypes: true,
    },
  );

  const threadData = threadsDir
    .map<MockThreadSearchResult | null>((threadId) => {
      if (threadId.isDirectory() && !threadId.name.startsWith(".")) {
        const threadData = JSON.parse(
          fs.readFileSync(
            path.resolve(`public/demo/threads/${threadId.name}/thread.json`),
            "utf8",
          ),
        ) as Record<string, unknown>;

        return {
          ...threadData,
          thread_id: threadId.name,
          updated_at:
            typeof threadData.updated_at === "string"
              ? threadData.updated_at
              : typeof threadData.created_at === "string"
                ? threadData.created_at
                : undefined,
        };
      }
      return null;
    })
    .filter((thread): thread is MockThreadSearchResult => thread !== null)
    .sort((a, b) => {
      const aTimestamp = a[sortBy];
      const bTimestamp = b[sortBy];
      const aValue = typeof aTimestamp === "string" ? Date.parse(aTimestamp) : 0;
      const bValue = typeof bTimestamp === "string" ? Date.parse(bTimestamp) : 0;
      return sortOrder === "asc" ? aValue - bValue : bValue - aValue;
    });

  const pagedThreads = threadData.slice(offset, offset + limit);
  return Response.json(pagedThreads);
}
