import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ModelControlScope = "task" | "turn" | "conversation";
export type ModelControlDecision = {
  status: "none" | "resolved" | "ambiguous" | "unavailable";
  scope: ModelControlScope | null;
  query: string;
  model_name: string | null;
  candidates: { name: string; label: string }[];
  task_offset?: number;
};

export function modelTaskInput(
  text: string,
  choice: ModelControlDecision | null,
) {
  if (
    !choice ||
    choice.scope === "task" ||
    !Number.isInteger(choice.task_offset)
  )
    return { text, additionalKwargs: {} };
  const body = Array.from(text).slice(choice.task_offset).join("").trim();
  return {
    text: body,
    additionalKwargs: {
      model_control: { version: 1, original_text: text, execution_text: body },
    },
  };
}

export function maySelectModel(text: string) {
  return /^(?:请|麻烦)?(?:你?(?:找|让|叫)|这次|本次|这一轮|以后|今后|接下来|用|使用|改用|换成|这个|这部分|这件事)|^(?:please\s+)?(?:ask\s|delegate to\s|use\s|from now on\s)/i.test(
    text.trim(),
  );
}

export async function resolveModelControl(
  text: string,
  selection: { model_name?: string; scope?: ModelControlScope } = {},
  signal?: AbortSignal,
): Promise<ModelControlDecision> {
  const response = await fetch(`${getBackendBaseURL()}/api/models/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: Array.from(text).slice(0, 4000).join(""),
      ...selection,
    }),
    signal,
  });
  if (!response.ok)
    await throwGatewayApiError(
      response,
      "Unable to check the model selection.",
    );
  return response.json() as Promise<ModelControlDecision>;
}
