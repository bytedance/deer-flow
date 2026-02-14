import fs from "fs";
import path from "path";

export function POST() {
  const threadsDir = fs.readdirSync(
    path.resolve(process.cwd(), "public/demo/threads"),
    {
      withFileTypes: true,
    },
  );
  const threadData = threadsDir
    .map((threadId) => {
      if (threadId.isDirectory() && !threadId.name.startsWith(".")) {
        const threadData = fs.readFileSync(
          path.resolve(`public/demo/threads/${threadId.name}/thread.json`),
          "utf8",
        );
        return {
          thread_id: threadId.name,
          values: JSON.parse(threadData).values,
        };
      }
      return false;
    })
    .filter(Boolean);
  return Response.json(threadData);
}
