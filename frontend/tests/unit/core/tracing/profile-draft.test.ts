import { describe, expect, it } from "@rstest/core";

import {
  buildProfileRequest,
  profileDraft,
} from "@/core/tracing/profile-draft";
import type { TracingProfile } from "@/core/tracing/types";

const profile: TracingProfile = {
  id: "shared",
  name: "QA",
  revision: 4,
  allowed_user_ids: ["alice"],
  providers: [
    {
      provider: "arize",
      endpoint: "https://otlp.arize.com",
      project: "qa",
      space_id: "space",
      transport: "http",
      has_api_key: true,
      has_secret_key: false,
    },
  ],
};

describe("tracing profile credential editing", () => {
  it("uses the Arize OTLP traces route for a new HTTP profile", () => {
    const draft = profileDraft(undefined, "admin-id");
    draft.name = "QA";
    draft.providers[0]!.project = "qa";
    draft.providers[0]!.space_id = "space";
    draft.providers[0]!.api_key = "new-key";
    expect(buildProfileRequest(draft).providers[0]).toEqual({
      provider: "arize",
      endpoint: "https://otlp.arize.com/v1/traces",
      project: "qa",
      space_id: "space",
      transport: "http",
      api_key: "new-key",
    });
  });

  it("preserves an explicitly configured gRPC collector endpoint", () => {
    const draft = profileDraft(undefined, "admin-id");
    draft.name = "QA";
    draft.providers[0]!.project = "qa";
    draft.providers[0]!.space_id = "space";
    draft.providers[0]!.api_key = "new-key";
    draft.providers[0]!.transport = "grpc";
    draft.providers[0]!.endpoint = "https://collector.example:4317";
    expect(buildProfileRequest(draft).providers[0]?.endpoint).toBe(
      "https://collector.example:4317",
    );
  });

  it("round-trips a LangSmith organization workspace while editing another field", () => {
    const existing: TracingProfile = {
      ...profile,
      providers: [
        {
          provider: "langsmith",
          endpoint: "https://api.smith.langchain.com",
          project: "qa",
          workspace_id: "workspace-a",
          has_api_key: true,
          has_secret_key: false,
        },
      ],
    };
    const draft = profileDraft(existing);
    draft.providers[0]!.project = "updated-project";
    expect(buildProfileRequest(draft, existing).providers[0]).toEqual({
      provider: "langsmith",
      endpoint: "https://api.smith.langchain.com",
      project: "updated-project",
      workspace_id: "workspace-a",
      transport: "http",
    });
    draft.providers[0]!.workspace_id = "";
    expect(
      buildProfileRequest(draft, existing).providers[0]?.workspace_id,
    ).toBe("");
  });

  it("omits workspace IDs from non-LangSmith providers", () => {
    const draft = profileDraft(profile);
    draft.providers[0]!.workspace_id = "inapplicable-workspace";
    expect(buildProfileRequest(draft, profile).providers[0]).not.toHaveProperty(
      "workspace_id",
    );
  });

  it("never seeds credentials from a saved profile and omits unchanged credentials", () => {
    const draft = profileDraft(profile);
    expect(draft.providers[0]?.api_key).toBe("");
    expect(buildProfileRequest(draft, profile)).toEqual({
      name: "QA",
      expected_revision: 4,
      allowed_user_ids: ["alice"],
      providers: [
        {
          provider: "arize",
          endpoint: "https://otlp.arize.com",
          project: "qa",
          space_id: "space",
          transport: "http",
        },
      ],
    });
  });

  it("requires a new key after an endpoint change", () => {
    const draft = profileDraft(profile);
    draft.providers[0]!.endpoint = "https://different.example";
    expect(() => buildProfileRequest(draft, profile)).toThrow(
      "credentials_required",
    );
    draft.providers[0]!.api_key = "replacement-key";
    expect(buildProfileRequest(draft, profile).providers[0]?.api_key).toBe(
      "replacement-key",
    );
  });

  it("requires a new key when switching Arize transport", () => {
    const draft = profileDraft(profile);
    draft.providers[0]!.transport = "grpc";
    expect(() => buildProfileRequest(draft, profile)).toThrow(
      "credentials_required",
    );
  });

  it("requires a new secret when changing a Langfuse public key", () => {
    const existing: TracingProfile = {
      ...profile,
      providers: [
        {
          provider: "langfuse",
          endpoint: "https://cloud.langfuse.com",
          public_key: "old-public",
          has_api_key: false,
          has_secret_key: true,
        },
      ],
    };
    const draft = profileDraft(existing);
    draft.providers[0]!.public_key = "new-public";
    expect(() => buildProfileRequest(draft, existing)).toThrow(
      "credentials_required",
    );
  });

  it("explains missing Arize destination fields before making a request", () => {
    const draft = profileDraft(profile);
    draft.providers[0]!.space_id = "";
    expect(() => buildProfileRequest(draft, profile)).toThrow(
      "arize_destination_required",
    );
  });

  it("keeps provider credentials matched by provider when adding another destination", () => {
    const draft = profileDraft(profile);
    draft.providers.unshift({
      provider: "langfuse",
      endpoint: "https://cloud.langfuse.com",
      project: "",
      space_id: "",
      public_key: "pk",
      transport: "http",
      api_key: "",
      secret_key: "new-secret",
      workspace_id: "",
    });
    const request = buildProfileRequest(draft, profile);
    expect(request.providers[0]?.secret_key).toBe("new-secret");
    expect(request.providers[1]).not.toHaveProperty("api_key");
  });

  it("does not grant access to everyone when allowed users are empty", () => {
    const draft = profileDraft(undefined, "admin-id");
    expect(draft.allowed_user_ids).toBe("admin-id");
    draft.allowed_user_ids = " alice, bob\nalice ";
    draft.providers[0]!.api_key = "key";
    draft.providers[0]!.space_id = "space";
    draft.providers[0]!.project = "qa";
    expect(buildProfileRequest(draft).allowed_user_ids).toEqual([
      "alice",
      "bob",
    ]);
  });
});
