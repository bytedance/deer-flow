import { expect, rs, test } from "@rstest/core";
import { QueryClient } from "@tanstack/react-query";

import { cacheLarkMutationStatus } from "@/core/integrations/lark/cache";
import { type LarkIntegrationStatus } from "@/core/integrations/lark/types";

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

test("mutation status cancels stale reads before populating an empty cache", () => {
  const queryClient = new QueryClient();
  const cancelQueries = rs.spyOn(queryClient, "cancelQueries");

  cacheLarkMutationStatus(queryClient, status);

  expect(cancelQueries).toHaveBeenCalledWith({
    queryKey: ["integrations", "lark"],
  });
  expect(queryClient.getQueryData(["integrations", "lark"])).toEqual(status);
});

test("unprobed mutation status preserves runtime fields from the authoritative GET", () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["integrations", "lark"], {
    ...status,
    auth: { ...status.auth, verified: false },
  });
  const mutationStatus: LarkIntegrationStatus = {
    ...status,
    // Different mode from the cached status, so the assertions below prove
    // the runtime fields came from the cache rather than the mutation.
    sandbox_runtime_mode: "gateway-download",
    sandbox_runtime_probed: false,
    sandbox_runtime_ready: false,
    sandbox_runtime_detail: null,
  };

  cacheLarkMutationStatus(queryClient, mutationStatus);

  expect(
    queryClient.getQueryData<LarkIntegrationStatus>(["integrations", "lark"]),
  ).toMatchObject({
    auth: { verified: true },
    sandbox_runtime_mode: "init-container",
    sandbox_runtime_probed: true,
    sandbox_runtime_ready: true,
    sandbox_runtime_detail: null,
  });
});

test("explicitly probed unready status does not depend on detail text", () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["integrations", "lark"], status);
  const mutationStatus: LarkIntegrationStatus = {
    ...status,
    sandbox_runtime_probed: true,
    sandbox_runtime_ready: false,
    sandbox_runtime_detail: null,
  };

  cacheLarkMutationStatus(queryClient, mutationStatus);

  expect(
    queryClient.getQueryData<LarkIntegrationStatus>(["integrations", "lark"]),
  ).toMatchObject({
    sandbox_runtime_probed: true,
    sandbox_runtime_ready: false,
    sandbox_runtime_detail: null,
  });
});

test("probed mutation status replaces older runtime fields", () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["integrations", "lark"], {
    ...status,
    sandbox_runtime_ready: false,
    sandbox_runtime_detail: "provisioner was unavailable",
  });
  const mutationStatus: LarkIntegrationStatus = {
    ...status,
    sandbox_runtime_mode: "broker",
    sandbox_runtime_probed: true,
  };

  cacheLarkMutationStatus(queryClient, mutationStatus);

  expect(
    queryClient.getQueryData<LarkIntegrationStatus>(["integrations", "lark"]),
  ).toMatchObject({
    sandbox_runtime_mode: "broker",
    sandbox_runtime_probed: true,
    sandbox_runtime_ready: true,
    sandbox_runtime_detail: null,
  });
});
