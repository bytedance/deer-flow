import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch } from "@/core/api/fetcher";
import {
  fetchUserSettings,
  initializeUserSettings,
  patchUserSettings,
} from "@/core/settings/api";

const mockedFetch = rs.mocked(fetch);
const settings = {
  notification: { enabled: true },
  tokenUsage: { headerTotal: true, inlineMode: "per_turn" as const },
  context: {},
};

function response(): Response {
  return new Response(JSON.stringify({ settings, revision: 1 }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
  mockedFetch.mockImplementation(async () => response());
});

describe("user settings API", () => {
  it("binds reads to the user that mounted the sync controller", async () => {
    await fetchUserSettings("user-a");

    expect(mockedFetch).toHaveBeenCalledWith("/api/user-preferences", {
      headers: { "X-DeerFlow-Expected-User-Id": "user-a" },
    });
  });

  it("binds initialization and patches to the same expected owner", async () => {
    await initializeUserSettings("user-a", settings);
    await patchUserSettings("user-a", {
      tokenUsage: { inlineMode: "off" },
    });

    expect(mockedFetch).toHaveBeenNthCalledWith(1, "/api/user-preferences", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-DeerFlow-Expected-User-Id": "user-a",
      },
      body: JSON.stringify({ settings }),
    });
    expect(mockedFetch).toHaveBeenNthCalledWith(2, "/api/user-preferences", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-DeerFlow-Expected-User-Id": "user-a",
      },
      body: JSON.stringify({ tokenUsage: { inlineMode: "off" } }),
    });
  });
});
