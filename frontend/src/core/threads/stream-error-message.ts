const INSUFFICIENT_CREDITS_CODE = "INSUFFICIENT_CREDITS";

function formatInsufficientCredits(candidate: unknown): string | null {
  if (
    typeof candidate !== "object" ||
    candidate === null ||
    Reflect.get(candidate, "code") !== INSUFFICIENT_CREDITS_CODE
  ) {
    return null;
  }

  const available = Reflect.get(candidate, "available_credits");
  const required = Reflect.get(candidate, "required_credits");
  return `积分不足：当前可用 ${available ?? 0} 积分，本次任务至少需要 ${required ?? "更多"} 积分。请先充值后重新发起任务。`;
}

function parseErrorDetail(message: string): unknown {
  const jsonStart = message.indexOf("{");
  if (jsonStart < 0) return undefined;

  try {
    const payload: unknown = JSON.parse(message.slice(jsonStart));
    if (typeof payload === "object" && payload !== null) {
      return Reflect.get(payload, "detail");
    }
  } catch {
    // The original message remains the best fallback for a non-JSON error.
  }
  return undefined;
}

export function getStreamErrorMessage(error: unknown): string {
  const errorMessage =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null
          ? Reflect.get(error, "message")
          : undefined;

  if (typeof error === "object" && error !== null) {
    const detail = Reflect.get(error, "detail");
    const nestedDetail = Reflect.get(
      Reflect.get(error, "response") ?? {},
      "detail",
    );
    for (const candidate of [detail, nestedDetail]) {
      const formatted = formatInsufficientCredits(candidate);
      if (formatted) return formatted;
    }
  }

  if (typeof errorMessage === "string") {
    const formatted = formatInsufficientCredits(parseErrorDetail(errorMessage));
    if (formatted) return formatted;
    if (errorMessage.trim()) return errorMessage;
  }

  if (typeof error === "object" && error !== null) {
    const nestedError = Reflect.get(error, "error");
    if (nestedError instanceof Error && nestedError.message.trim()) {
      return getStreamErrorMessage(nestedError);
    }
    if (typeof nestedError === "string" && nestedError.trim()) {
      return getStreamErrorMessage(nestedError);
    }
  }

  return "Request failed.";
}
