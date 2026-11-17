/**
 * Whether closing the incognito frame must ask the Gateway to end the chat.
 *
 * `isNewThread` flips only when the first run starts, but a project/incognito
 * pre-create (or a `/goal` command) materializes the thread row earlier. The
 * decision therefore follows the row, not the flag: a lazy chat that never
 * created a row has nothing to end, while a pre-created one must still be
 * ended before the frame navigates away.
 */
export function shouldRequestIncognitoEnd({
  isNewThread,
  isMock,
  threadId,
  createdThreadId,
}: {
  isNewThread: boolean;
  isMock: boolean;
  threadId: string;
  createdThreadId: string | null;
}): boolean {
  if (isMock) return false;
  return !isNewThread || createdThreadId === threadId;
}