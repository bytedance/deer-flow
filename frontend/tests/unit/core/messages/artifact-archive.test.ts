import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import { getArtifactArchiveCandidatesByGroupIndex } from "@/core/messages/artifact-archive";
import { getMessageGroups } from "@/core/messages/utils";

function presentFiles(id: string, runId: string, filepaths: string[]): Message {
  return {
    id,
    type: "ai",
    content: "",
    run_id: runId,
    tool_calls: [
      {
        id: `call-${id}`,
        name: "present_files",
        args: { filepaths },
      },
    ],
  } as Message;
}

describe("artifact archive display placement", () => {
  test("anchors one archive action after a run's final file presentation", () => {
    const groups = getMessageGroups([
      presentFiles("first", "run-1", ["/mnt/user-data/outputs/a.txt"]),
      presentFiles("second", "run-1", [
        "/mnt/user-data/outputs/a.txt",
        "/mnt/user-data/outputs/b.txt",
      ]),
    ]);

    expect(getArtifactArchiveCandidatesByGroupIndex(groups)).toEqual([
      undefined,
      { runId: "run-1" },
    ]);
  });

  test("verifies even a single attempted path against the terminal receipt", () => {
    const groups = getMessageGroups([
      presentFiles("only", "run-1", ["/mnt/user-data/outputs/a.txt"]),
    ]);

    expect(getArtifactArchiveCandidatesByGroupIndex(groups)).toEqual([
      { runId: "run-1" },
    ]);
  });

  test("keeps archive actions independent across runs", () => {
    const groups = getMessageGroups([
      presentFiles("run-1-first", "run-1", ["/mnt/user-data/outputs/a.txt"]),
      presentFiles("run-2", "run-2", [
        "/mnt/user-data/outputs/c.txt",
        "/mnt/user-data/outputs/d.txt",
      ]),
      presentFiles("run-1-last", "run-1", ["/mnt/user-data/outputs/b.txt"]),
    ]);

    expect(getArtifactArchiveCandidatesByGroupIndex(groups)).toEqual([
      undefined,
      { runId: "run-2" },
      { runId: "run-1" },
    ]);
  });
});
