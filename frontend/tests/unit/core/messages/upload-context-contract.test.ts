import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import { hasStructuredUploadContext } from "@/core/messages/utils";

interface ContractCase {
  name: string;
  message_type: "human" | "ai";
  metadata?: unknown;
  valid: boolean;
}
const contract = JSON.parse(
  readFileSync(
    resolve(__dirname, "../../../../../contracts/upload_context_contract.json"),
    "utf-8",
  ),
) as { metadata_key: string; cases: ContractCase[] };

describe("shared upload-context contract", () => {
  it.each(contract.cases)("validates the shared case %j", (testCase) => {
    const message = {
      type: testCase.message_type,
      content: "User text",
      additional_kwargs:
        "metadata" in testCase
          ? { [contract.metadata_key]: testCase.metadata }
          : {},
    } as Message;
    expect(hasStructuredUploadContext(message)).toBe(testCase.valid);
  });
});
