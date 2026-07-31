import { randomUUID } from "crypto";
import fs from "fs";
import path from "path";

import { afterEach, beforeEach, describe, expect, test } from "@rstest/core";
import { NextRequest } from "next/server";

import { GET as getMcpConfig } from "@/app/mock/api/mcp/config/route";
import { GET as getModels } from "@/app/mock/api/models/route";
import { GET as getSkills } from "@/app/mock/api/skills/route";
import { GET as getArtifact } from "@/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route";
import { POST as getHistory } from "@/app/mock/api/threads/[thread_id]/history/route";
import { POST as searchThreads } from "@/app/mock/api/threads/search/route";

const DEMO_THREAD_ID = "21cfea46-34bd-4aa6-9e1f-3009452fbeb9";

const savedEnv = {
  NODE_ENV: process.env.NODE_ENV,
  DEER_FLOW_ENABLE_MOCK_API: process.env.DEER_FLOW_ENABLE_MOCK_API,
};

function setEnv(name: string, value: string | undefined) {
  if (value === undefined) {
    delete process.env[name];
  } else {
    process.env[name] = value;
  }
}

describe("mock API production boundary", () => {
  beforeEach(() => {
    setEnv("NODE_ENV", "production");
    setEnv("DEER_FLOW_ENABLE_MOCK_API", undefined);
  });

  afterEach(() => {
    setEnv("NODE_ENV", savedEnv.NODE_ENV);
    setEnv("DEER_FLOW_ENABLE_MOCK_API", savedEnv.DEER_FLOW_ENABLE_MOCK_API);
  });

  test("returns 404 from every mock handler before demo data is accessed", async () => {
    const immediateResponses = [getMcpConfig(), getModels(), getSkills()];
    const asyncResponses = await Promise.all([
      getHistory(new NextRequest("http://localhost/mock/history"), {
        params: Promise.resolve({ thread_id: DEMO_THREAD_ID }),
      }),
      searchThreads(
        new Request("http://localhost/mock/api/threads/search", {
          method: "POST",
          body: "{}",
          headers: { "Content-Type": "application/json" },
        }),
      ),
      getArtifact(
        new NextRequest(
          `http://localhost/mock/api/threads/${DEMO_THREAD_ID}/artifacts/mnt/user-data/outputs/doraemon-moe-comic.jpg`,
        ),
        {
          params: Promise.resolve({
            thread_id: DEMO_THREAD_ID,
            artifact_path: [
              "mnt",
              "user-data",
              "outputs",
              "doraemon-moe-comic.jpg",
            ],
          }),
        },
      ),
    ]);
    const responses = [...immediateResponses, ...asyncResponses];

    expect(responses.map((response) => response.status)).toEqual([
      404, 404, 404, 404, 404, 404,
    ]);
  });

  test("allows an explicit production opt-in", async () => {
    setEnv("DEER_FLOW_ENABLE_MOCK_API", "true");

    const response = getModels();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      models: expect.any(Array),
    });
  });

  test("does not serve an artifact outside its demo thread directory", async () => {
    setEnv("DEER_FLOW_ENABLE_MOCK_API", "true");

    const response = await getArtifact(
      new NextRequest(
        `http://localhost/mock/api/threads/${DEMO_THREAD_ID}/artifacts/mnt/../../../../package.json`,
      ),
      {
        params: Promise.resolve({
          thread_id: DEMO_THREAD_ID,
          artifact_path: ["mnt", "..", "..", "..", "..", "package.json"],
        }),
      },
    );

    expect(response.status).toBe(404);
  });

  test("does not read history outside a UUID thread directory", async () => {
    setEnv("DEER_FLOW_ENABLE_MOCK_API", "true");
    const externalThreadName = `outside-thread-${randomUUID()}`;
    const externalThreadDirectory = path.resolve(
      process.cwd(),
      "public",
      "demo",
      externalThreadName,
    );
    const escapedHistoryPath = path.join(
      externalThreadDirectory,
      "thread.json",
    );
    fs.mkdirSync(externalThreadDirectory);
    fs.writeFileSync(escapedHistoryPath, JSON.stringify({ history: [] }));

    try {
      const response = await getHistory(
        new NextRequest("http://localhost/mock/api/threads/invalid/history"),
        {
          params: Promise.resolve({
            thread_id: `../${externalThreadName}`,
          }),
        },
      );

      expect(response.status).toBe(404);
    } finally {
      fs.unlinkSync(escapedHistoryPath);
      fs.rmdirSync(externalThreadDirectory);
    }
  });

  test("does not follow a thread directory symlink outside the threads root", async () => {
    setEnv("DEER_FLOW_ENABLE_MOCK_API", "true");
    const linkedThreadId = randomUUID();
    const linkedThreadDirectory = path.resolve(
      process.cwd(),
      "public",
      "demo",
      "threads",
      linkedThreadId,
    );
    const externalDirectory = path.resolve(
      process.cwd(),
      "public",
      "demo",
      `outside-thread-${linkedThreadId}`,
    );
    const externalArtifact = path.join(externalDirectory, "secret.txt");
    fs.mkdirSync(externalDirectory);
    fs.writeFileSync(externalArtifact, "not a demo thread artifact");
    fs.symlinkSync(
      externalDirectory,
      linkedThreadDirectory,
      process.platform === "win32" ? "junction" : "dir",
    );

    try {
      const response = await getArtifact(
        new NextRequest(
          `http://localhost/mock/api/threads/${linkedThreadId}/artifacts/mnt/secret.txt`,
        ),
        {
          params: Promise.resolve({
            thread_id: linkedThreadId,
            artifact_path: ["mnt", "secret.txt"],
          }),
        },
      );

      expect(response.status).toBe(404);
    } finally {
      fs.unlinkSync(linkedThreadDirectory);
      fs.unlinkSync(externalArtifact);
      fs.rmdirSync(externalDirectory);
    }
  });

  test("does not follow a nested symlink outside a valid thread directory", async () => {
    setEnv("DEER_FLOW_ENABLE_MOCK_API", "true");
    const threadId = randomUUID();
    const threadDirectory = path.resolve(
      process.cwd(),
      "public",
      "demo",
      "threads",
      threadId,
    );
    const externalDirectory = path.resolve(
      process.cwd(),
      "public",
      "demo",
      `outside-thread-${threadId}`,
    );
    const linkedDirectory = path.join(threadDirectory, "linked");
    const externalArtifact = path.join(externalDirectory, "secret.txt");
    fs.mkdirSync(threadDirectory);
    fs.mkdirSync(externalDirectory);
    fs.writeFileSync(externalArtifact, "not a demo thread artifact");
    fs.symlinkSync(
      externalDirectory,
      linkedDirectory,
      process.platform === "win32" ? "junction" : "dir",
    );

    try {
      const response = await getArtifact(
        new NextRequest(
          `http://localhost/mock/api/threads/${threadId}/artifacts/mnt/linked/secret.txt`,
        ),
        {
          params: Promise.resolve({
            thread_id: threadId,
            artifact_path: ["mnt", "linked", "secret.txt"],
          }),
        },
      );

      expect(response.status).toBe(404);
    } finally {
      fs.unlinkSync(linkedDirectory);
      fs.rmdirSync(threadDirectory);
      fs.unlinkSync(externalArtifact);
      fs.rmdirSync(externalDirectory);
    }
  });

  test("serves valid demo files when production mock access is enabled", async () => {
    setEnv("DEER_FLOW_ENABLE_MOCK_API", "true");

    const [historyResponse, artifactResponse] = await Promise.all([
      getHistory(new NextRequest("http://localhost/mock/history"), {
        params: Promise.resolve({ thread_id: DEMO_THREAD_ID }),
      }),
      getArtifact(
        new NextRequest(
          `http://localhost/mock/api/threads/${DEMO_THREAD_ID}/artifacts/mnt/user-data/outputs/doraemon-moe-comic.jpg?download=true`,
        ),
        {
          params: Promise.resolve({
            thread_id: DEMO_THREAD_ID,
            artifact_path: [
              "mnt",
              "user-data",
              "outputs",
              "doraemon-moe-comic.jpg",
            ],
          }),
        },
      ),
    ]);

    expect(historyResponse.status).toBe(200);
    expect(artifactResponse.status).toBe(200);
    expect(artifactResponse.headers.get("Content-Disposition")).toBe(
      'attachment; filename="doraemon-moe-comic.jpg"',
    );
  });
});
