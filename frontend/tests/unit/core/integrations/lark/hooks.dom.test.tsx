import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/integrations/lark/api", () => ({
  completeLarkAuthorization: rs.fn(),
  completeLarkConfiguration: rs.fn(),
  installLarkIntegration: rs.fn(),
  loadLarkIntegrationStatus: rs.fn(),
  setLarkAppCredentials: rs.fn(),
  startLarkAuthorization: rs.fn(),
  startLarkConfiguration: rs.fn(),
}));

import { installLarkIntegration } from "@/core/integrations/lark/api";
import { useInstallLarkIntegration } from "@/core/integrations/lark/hooks";
import type { LarkIntegrationStatus } from "@/core/integrations/lark/types";

const mockedInstall = rs.mocked(installLarkIntegration);

const status: LarkIntegrationStatus = {
  installed: true,
  version: "v1.0.65",
  manifest_version: "v1.0.65",
  latest_available_version: null,
  runtime_version_mismatch: false,
  app_configured: true,
  app_id: "cli_mock",
  app_brand: "feishu",
  skills_expected: 27,
  skills_installed: 27,
  installed_skills: ["lark-doc"],
  enabled_skills: ["lark-doc"],
  install_path: "/tmp/lark",
  cli: {
    available: true,
    path: "/usr/bin/lark-cli",
    version: "v1.0.65",
    error: null,
  },
  auth: {
    status: "authenticated",
    message: null,
    user: "Alice",
    verified: true,
  },
  sandbox_runtime_mode: "init-container",
  sandbox_runtime_probed: true,
  sandbox_runtime_ready: true,
  sandbox_runtime_detail: null,
};

afterEach(() => {
  cleanup();
  mockedInstall.mockReset();
});

describe("useInstallLarkIntegration", () => {
  it("writes the mutation status through cacheLarkMutationStatus", async () => {
    // Regression guard: the install mutation must cancel stale in-flight
    // reads (i.e. go through cacheLarkMutationStatus) instead of a bare
    // setQueryData, so version-skewed unprobed responses cannot clobber the
    // authoritative runtime fields.
    mockedInstall.mockResolvedValueOnce({
      success: true,
      installed_skills: ["lark-doc"],
      message: "Installed 1 Lark/Feishu skills.",
      status,
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const cancelQueries = rs.spyOn(queryClient, "cancelQueries");
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useInstallLarkIntegration(), {
      wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(cancelQueries).toHaveBeenCalledWith({
      queryKey: ["integrations", "lark"],
    });
    expect(queryClient.getQueryData(["integrations", "lark"])).toEqual(status);
  });
});
