export function shouldClearOptimisticMessages({
  optimisticCount,
  serverMessages,
}) {
  if (optimisticCount <= 0) {
    return false;
  }

  return serverMessages.some((message) => message?.type === "human");
}
