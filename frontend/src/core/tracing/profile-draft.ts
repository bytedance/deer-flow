import type {
  SaveTracingProfileRequest,
  TracingProfile,
  TracingProvider,
} from "./types";

export interface ProviderDraft {
  provider: TracingProvider;
  endpoint: string;
  project: string;
  space_id: string;
  workspace_id: string;
  public_key: string;
  transport: "http" | "grpc";
  api_key: string;
  secret_key: string;
}
export interface ProfileDraft {
  name: string;
  allowed_user_ids: string;
  providers: ProviderDraft[];
}

export const PROVIDER_NAMES: Record<TracingProvider, string> = {
  arize: "Arize",
  langsmith: "LangSmith",
  langfuse: "Langfuse",
};

export function providerDraft(provider: TracingProvider): ProviderDraft {
  return {
    provider,
    endpoint: {
      arize: "https://otlp.arize.com/v1/traces",
      langsmith: "https://api.smith.langchain.com",
      langfuse: "https://cloud.langfuse.com",
    }[provider],
    project: "",
    space_id: "",
    workspace_id: "",
    public_key: "",
    transport: "http",
    api_key: "",
    secret_key: "",
  };
}

export function profileDraft(
  profile?: TracingProfile,
  userId = "",
): ProfileDraft {
  return {
    name: profile?.name ?? "",
    allowed_user_ids: profile?.allowed_user_ids.join(", ") ?? userId,
    providers: profile?.providers.map((item) => ({
      ...providerDraft(item.provider),
      endpoint: item.endpoint ?? "",
      project: item.project ?? "",
      space_id: item.space_id ?? "",
      workspace_id: item.workspace_id ?? "",
      public_key: item.public_key ?? "",
      transport: item.transport ?? "http",
    })) ?? [providerDraft("arize")],
  };
}

export function buildProfileRequest(
  draft: ProfileDraft,
  profile?: TracingProfile,
): SaveTracingProfileRequest {
  if (draft.providers.length === 0) throw new Error("provider_required");
  return {
    name: draft.name.trim(),
    expected_revision: profile?.revision ?? 0,
    allowed_user_ids: [
      ...new Set(draft.allowed_user_ids.split(/[\s,]+/).filter(Boolean)),
    ],
    providers: draft.providers.map((item) => {
      if (
        item.provider === "arize" &&
        (!item.project.trim() || !item.space_id.trim())
      )
        throw new Error("arize_destination_required");
      const previous = profile?.providers.find(
        (saved) => saved.provider === item.provider,
      );
      const canKeep =
        previous?.endpoint === item.endpoint.trim() &&
        (previous?.transport ?? "http") === item.transport;
      if (item.provider === "langfuse") {
        if (
          !item.public_key.trim() ||
          (!item.secret_key.trim() &&
            !(
              canKeep &&
              previous?.has_secret_key &&
              previous.public_key === item.public_key.trim()
            ))
        )
          throw new Error("credentials_required");
      } else if (!item.api_key.trim() && !(canKeep && previous?.has_api_key)) {
        throw new Error("credentials_required");
      }
      return {
        provider: item.provider,
        endpoint: item.endpoint.trim(),
        transport: item.transport,
        ...(item.project.trim() ? { project: item.project.trim() } : {}),
        ...(item.provider === "arize" && item.space_id.trim()
          ? { space_id: item.space_id.trim() }
          : {}),
        ...(item.provider === "langsmith"
          ? { workspace_id: item.workspace_id.trim() }
          : {}),
        ...(item.provider === "langfuse"
          ? { public_key: item.public_key.trim() }
          : {}),
        ...(item.api_key.trim() ? { api_key: item.api_key.trim() } : {}),
        ...(item.secret_key.trim()
          ? { secret_key: item.secret_key.trim() }
          : {}),
      };
    }),
  };
}
