import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  createManagedSubagent,
  listSubagents,
  updateManagedSubagent,
} from "@/core/subagents/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("managed subagent API", () => {
  test("lists the mixed-source catalog", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        subagents: [
          {
            name: "general-purpose",
            description: "General worker",
            source: "builtin",
            enabled: true,
          },
        ],
      }),
    );
    await expect(listSubagents()).resolves.toHaveLength(1);
  });

  test("creates and updates managed definitions through admin endpoints", async () => {
    mockedFetch
      .mockResolvedValueOnce(
        jsonResponse(201, {
          name: "planner",
          description: "Plans",
          source: "managed",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          name: "planner",
          description: "Plans",
          source: "managed",
          enabled: false,
        }),
      );

    await createManagedSubagent({
      name: "planner",
      description: "Plans",
      system_prompt: "You plan.",
    });
    await updateManagedSubagent("planner", { enabled: false });

    expect(mockedFetch.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(mockedFetch.mock.calls[1]?.[1]?.method).toBe("PUT");
    expect(JSON.parse(mockedFetch.mock.calls[1]?.[1]?.body as string)).toEqual({
      enabled: false,
    });
  });

  test("surfaces backend conflict details", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(409, { detail: "Subagent name is reserved" }),
    );
    await expect(
      createManagedSubagent({
        name: "general-purpose",
        description: "Duplicate",
        system_prompt: "Duplicate",
      }),
    ).rejects.toThrow("Subagent name is reserved");
  });

  test("formats FastAPI validation detail arrays", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(422, {
        detail: [{ loc: ["body", "name"], msg: "String should match pattern" }],
      }),
    );
    await expect(
      createManagedSubagent({
        name: "invalid_name",
        description: "Invalid",
        system_prompt: "Invalid",
      }),
    ).rejects.toThrow("String should match pattern");
  });
});
