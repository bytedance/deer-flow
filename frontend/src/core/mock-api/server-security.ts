import fs from "fs";
import path from "path";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isContainedPath(parent: string, candidate: string): boolean {
  const relativePath = path.relative(parent, candidate);
  return (
    relativePath !== "" &&
    relativePath !== ".." &&
    !relativePath.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relativePath)
  );
}

export function rejectDisabledMockApi(): Response | null {
  if (
    process.env.NODE_ENV === "production" &&
    process.env.DEER_FLOW_ENABLE_MOCK_API !== "true"
  ) {
    return new Response("Not found", { status: 404 });
  }
  return null;
}

export function resolveDemoThreadFile(
  threadId: string,
  relativePathSegments: string[],
): string | null {
  if (
    !UUID_PATTERN.test(threadId) ||
    relativePathSegments.length === 0 ||
    relativePathSegments.some(
      (segment) =>
        segment === "" ||
        segment === "." ||
        segment === ".." ||
        segment.includes("/") ||
        segment.includes("\\") ||
        segment.includes("\0"),
    )
  ) {
    return null;
  }

  const threadsDirectory = path.resolve(
    process.cwd(),
    "public",
    "demo",
    "threads",
  );
  const threadDirectory = path.resolve(threadsDirectory, threadId);
  const candidate = path.resolve(threadDirectory, ...relativePathSegments);

  if (!isContainedPath(threadDirectory, candidate)) {
    return null;
  }

  try {
    const threadStats = fs.lstatSync(threadDirectory);
    if (!threadStats.isDirectory() || threadStats.isSymbolicLink()) {
      return null;
    }

    const realThreadsDirectory = fs.realpathSync(threadsDirectory);
    const realThreadDirectory = fs.realpathSync(threadDirectory);
    const realCandidate = fs.realpathSync(candidate);
    if (
      !isContainedPath(realThreadsDirectory, realThreadDirectory) ||
      !isContainedPath(realThreadDirectory, realCandidate) ||
      !fs.statSync(realCandidate).isFile()
    ) {
      return null;
    }

    return realCandidate;
  } catch {
    return null;
  }
}
