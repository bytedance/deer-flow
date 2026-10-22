import { expect, test } from "@playwright/test";

import type {
  AgentTracing,
  SaveAgentTracingRequest,
  SaveTracingProfileRequest,
  TracingProfile,
} from "@/core/tracing/types";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 640 },
]) {
  test(`agent tracing saves independently and preserves a conflicted draft at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    mockLangGraphAPI(page, { agents: [{ name: "research" }] });
    const profile: TracingProfile = {
      id: "qa",
      name: "QA profile",
      revision: 1,
      allowed_user_ids: ["default"],
      providers: [
        {
          provider: "arize",
          endpoint: "https://otlp.arize.com",
          project: "qa-project",
          space_id: "qa-space",
          transport: "http",
          has_api_key: true,
          has_secret_key: false,
        },
      ],
    };
    let binding: AgentTracing = {
      mode: "inherit",
      profile_id: null,
      revision: 0,
      effective_revision: "global:1",
      source: "global",
      destinations: [],
      status: "pending",
      error: null,
      delivery_verified: false,
      can_select: true,
    };
    const saves: SaveAgentTracingRequest[] = [];
    const profileSaves: SaveTracingProfileRequest[] = [];
    await page.route("**/api/tracing/profiles", (route) =>
      route.fulfill({
        json: {
          profiles: [profile],
          can_manage: true,
          available: true,
          reason: null,
        },
      }),
    );
    await page.route("**/api/tracing/profiles/qa", async (route) => {
      profileSaves.push(
        route.request().postDataJSON() as SaveTracingProfileRequest,
      );
      await route.fulfill({ json: { ...profile, revision: 2 } });
    });
    await page.route("**/api/agents/research/tracing", async (route) => {
      if (route.request().method() === "GET")
        return route.fulfill({ json: binding });
      const body = route.request().postDataJSON() as SaveAgentTracingRequest;
      saves.push(body);
      if (saves.length > 1)
        return route.fulfill({
          status: 409,
          json: { detail: { code: "revision_conflict", message: "Changed" } },
        });
      binding = {
        ...binding,
        mode: body.mode,
        profile_id: body.profile_id,
        revision: 1,
        effective_revision: "qa:1",
        source: "qa",
        destinations: [
          {
            provider: "arize",
            endpoint: "https://otlp.arize.com",
            project: "qa-project",
            space_id: "qa-space",
          },
        ],
      };
      return route.fulfill({ json: binding });
    });
    await page.goto("/workspace/agents");
    await page.getByTitle("Agent settings", { exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Agent settings" });
    await dialog.getByRole("combobox", { name: "Tracing mode" }).click();
    await page
      .getByRole("option", { name: "Configured profile", exact: true })
      .click();
    await dialog.getByRole("combobox", { name: "Tracing profile" }).click();
    await page.getByRole("option", { name: "QA profile", exact: true }).click();
    await dialog
      .getByRole("button", { name: "Apply tracing", exact: true })
      .click();
    await expect(
      dialog.getByText("Tracing settings saved.", { exact: false }),
    ).toBeVisible();
    expect(saves[0]).toEqual({
      mode: "configured",
      profile_id: "qa",
      expected_revision: 0,
    });
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText("Arize · qa-project", { exact: true }),
    ).toBeVisible();
    await expect(
      dialog.getByText("Delivery has not been verified.", { exact: true }),
    ).toBeVisible();

    await dialog.getByText("Manage tracing profiles", { exact: true }).click();
    await dialog
      .getByRole("button", { name: "Edit QA profile", exact: true })
      .click();
    await expect(
      dialog.getByLabel("Arize API key", { exact: true }),
    ).toHaveValue("");
    await dialog
      .getByRole("button", { name: "Save profile", exact: true })
      .click();
    await expect.poll(() => profileSaves.length).toBe(1);
    expect(profileSaves[0]?.providers[0]).not.toHaveProperty("api_key");

    await dialog.getByRole("combobox", { name: "Tracing mode" }).click();
    await page.getByRole("option", { name: "Disabled", exact: true }).click();
    await dialog
      .getByRole("button", { name: "Apply tracing", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toContainText("changed elsewhere");
    await expect(
      dialog.getByRole("combobox", { name: "Tracing mode" }),
    ).toContainText("Disabled");
    const footerSave = dialog.getByRole("button", {
      name: "Save",
      exact: true,
    });
    await expect(footerSave).toBeInViewport();
    await expect(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeInViewport();
  });
}
