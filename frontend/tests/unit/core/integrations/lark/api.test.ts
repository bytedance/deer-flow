import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  completeLarkAuthorization,
  completeLarkConfiguration,
  installLarkIntegration,
  LarkIntegrationRequestError,
  loadLarkIntegrationStatus,
  startLarkAuthorization,
  startLarkConfiguration,
} from "@/core/integrations/lark/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Bad Request" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("lark integration api", () => {
  test("loads status", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        installed: false,
        version: "v1.0.65",
        manifest_version: null,
        latest_available_version: "v1.0.65",
        runtime_version_mismatch: false,
        app_configured: false,
        app_id: null,
        app_brand: null,
        skills_expected: 27,
        skills_installed: 0,
        installed_skills: [],
        enabled_skills: [],
        install_path: "/tmp/lark-cli",
        cli: { available: false, path: null, version: null, error: "missing" },
        auth: { status: "unavailable", message: "missing", user: null },
        sandbox_runtime_mode: "init-container",
        sandbox_runtime_ready: false,
        sandbox_runtime_detail: "init image not configured",
      }),
    );

    await expect(loadLarkIntegrationStatus()).resolves.toMatchObject({
      installed: false,
      version: "v1.0.65",
      sandbox_runtime_mode: "init-container",
      sandbox_runtime_ready: false,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/integrations/lark/status",
    );
  });

  test("installs integration", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        success: true,
        installed_skills: ["lark-doc"],
        message: "Installed 1 Lark/Feishu skills.",
        status: {
          installed: true,
          version: "v1.0.65",
          manifest_version: "v1.0.65",
          latest_available_version: "v1.0.65",
          runtime_version_mismatch: false,
          app_configured: false,
          app_id: null,
          app_brand: null,
          skills_expected: 27,
          skills_installed: 1,
          installed_skills: ["lark-doc"],
          enabled_skills: ["lark-doc"],
          install_path: "/tmp/lark-cli",
          cli: {
            available: true,
            path: "/usr/bin/lark-cli",
            version: "v1.0.65",
            error: null,
          },
          auth: {
            status: "not_configured",
            message: "not configured",
            user: null,
          },
        },
      }),
    );

    await expect(installLarkIntegration()).resolves.toMatchObject({
      success: true,
      installed_skills: ["lark-doc"],
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/integrations/lark/install",
      { method: "POST" },
    );
  });

  test("surfaces admin-required install errors", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "Admin privileges required." }),
    );

    const promise = installLarkIntegration();
    await expect(promise).rejects.toMatchObject({
      name: "LarkIntegrationRequestError",
      status: 403,
      isAdminRequired: true,
      message: "Admin privileges required.",
    });
    await expect(promise).rejects.toBeInstanceOf(LarkIntegrationRequestError);
  });

  test("starts browser authorization", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        verification_url: "https://open.feishu.cn/auth/mock",
        device_code: "device-code",
        expires_in: 600,
        user_code: null,
        hint: null,
      }),
    );

    await expect(
      startLarkAuthorization({
        recommend: true,
        domains: ["calendar"],
        scope: "calendar:calendar.event:read",
      }),
    ).resolves.toEqual({
      verification_url: "https://open.feishu.cn/auth/mock",
      device_code: "device-code",
      expires_in: 600,
      user_code: null,
      hint: null,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/integrations/lark/auth/start",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recommend: true,
          domains: ["calendar"],
          scope: "calendar:calendar.event:read",
        }),
      },
    );
  });

  test("starts connection setup", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        verification_url: "https://open.feishu.cn/page/cli?user_code=config",
        device_code: "config-device-code",
        expires_in: 600,
        interval: 5,
        user_code: "config",
        brand: "feishu",
      }),
    );

    await expect(startLarkConfiguration({ brand: "feishu" })).resolves.toEqual({
      verification_url: "https://open.feishu.cn/page/cli?user_code=config",
      device_code: "config-device-code",
      expires_in: 600,
      interval: 5,
      user_code: "config",
      brand: "feishu",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/integrations/lark/config/start",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand: "feishu" }),
      },
    );
  });

  test("completes connection setup", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        success: true,
        message: "Lark/Feishu connection setup completed.",
        status: {
          installed: true,
          version: "v1.0.65",
          manifest_version: "v1.0.65",
          latest_available_version: "v1.0.65",
          runtime_version_mismatch: false,
          app_configured: true,
          app_id: "cli_mock",
          app_brand: "feishu",
          skills_expected: 27,
          skills_installed: 1,
          installed_skills: ["lark-doc"],
          enabled_skills: ["lark-doc"],
          install_path: "/tmp/lark-cli",
          cli: {
            available: true,
            path: "/usr/bin/lark-cli",
            version: "v1.0.65",
            error: null,
          },
          auth: {
            status: "not_authorized",
            message: "not authorized",
            user: null,
          },
        },
      }),
    );

    await expect(
      completeLarkConfiguration({
        device_code: "config-device-code",
        brand: "feishu",
        interval: 5,
        expires_in: 600,
      }),
    ).resolves.toMatchObject({
      success: true,
      status: { app_configured: true, app_id: "cli_mock" },
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/integrations/lark/config/complete",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_code: "config-device-code",
          brand: "feishu",
          interval: 5,
          expires_in: 600,
        }),
      },
    );
  });

  test("completes browser authorization", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        success: true,
        message: "Lark/Feishu authorization completed.",
        status: {
          installed: true,
          version: "v1.0.65",
          manifest_version: "v1.0.65",
          latest_available_version: "v1.0.65",
          runtime_version_mismatch: false,
          app_configured: true,
          app_id: "cli_mock",
          app_brand: "feishu",
          skills_expected: 27,
          skills_installed: 1,
          installed_skills: ["lark-doc"],
          enabled_skills: ["lark-doc"],
          install_path: "/tmp/lark-cli",
          cli: {
            available: true,
            path: "/usr/bin/lark-cli",
            version: "v1.0.65",
            error: null,
          },
          auth: {
            status: "authenticated",
            message: "ok",
            user: "Alice",
          },
        },
      }),
    );

    await expect(
      completeLarkAuthorization({ device_code: "device-code" }),
    ).resolves.toMatchObject({
      success: true,
      status: { auth: { status: "authenticated", user: "Alice" } },
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/integrations/lark/auth/complete",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_code: "device-code" }),
      },
    );
  });
});
