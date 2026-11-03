export function isErrorDetailRecord(
  value: unknown,
): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function readSkillErrorDetail(
  response: Response,
): Promise<unknown> {
  const data: unknown = await response.json().catch(() => null);
  return isErrorDetailRecord(data) ? data.detail : undefined;
}
