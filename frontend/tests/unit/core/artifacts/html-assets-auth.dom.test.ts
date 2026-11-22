import { afterEach, expect, rs, test } from "@rstest/core";

import { prepareHtmlPreview } from "@/core/artifacts/html-assets";

rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));

afterEach(() => {
  rs.restoreAllMocks();
});

test("keeps resource 401 responses local to the preview without navigating to login", async () => {
  const navigate = rs
    .spyOn(window.location, "href", "set")
    .mockImplementation(() => undefined);
  const request = rs.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response('{"detail":"Unauthorized"}', {
      status: 401,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const url =
    "https://app.example/gateway/api/threads/chat/artifacts/mnt/user-data/outputs/report.html";
  const result = await prepareHtmlPreview(
    '<h1>Report</h1><img src="chart.png">',
    url,
  );
  expect(result.failedResources).toBe(1);
  expect(result.content).toContain("Report");
  expect(result.content).toContain('src="data:,"');
  expect(navigate).not.toHaveBeenCalled();
  expect(request).toHaveBeenCalledWith(
    url.replace("report.html", "chart.png"),
    expect.objectContaining({ credentials: "include", redirect: "error" }),
  );
});
