import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import { loadSkillDetails } from "@/core/skills/api";

const mockedFetch = rs.mocked(fetcher);

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("loadSkillDetails", () => {
  test("loads complete Markdown only when the user expands a skill", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ name: "demo", content: "# Full instructions" }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await expect(loadSkillDetails("demo")).resolves.toMatchObject({
      content: "# Full instructions",
    });
    expect(mockedFetch).toHaveBeenCalledWith("/api/skills/demo/details");
  });
});
