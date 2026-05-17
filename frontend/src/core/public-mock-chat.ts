const PUBLIC_MOCK_CHAT_PATH_PATTERN =
  /^\/workspace\/chats\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

export function getPublicMockChatThreadId(
  pathname: string | null,
  search: string | null,
) {
  const match = pathname?.match(PUBLIC_MOCK_CHAT_PATH_PATTERN);
  if (!match) {
    return null;
  }
  if (new URLSearchParams(search ?? "").get("mock") !== "true") {
    return null;
  }
  return match[1] ?? null;
}
