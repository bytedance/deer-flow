/** Dispatch owns the card key; learning an execution ID never changes it. */
export function subtaskKey(callId: string, dispatchId?: string): string {
  return dispatchId ? JSON.stringify([dispatchId, callId]) : callId;
}

export function readTaskIdentity(value: Record<string, unknown>, prefix = "") {
  const text = (key: string) => {
    const item = value[prefix + key];
    return typeof item === "string" && item.trim() ? item : undefined;
  };
  const identity = {
    dispatchId: text("dispatch_id"),
    executionId: text("execution_id"),
    executor: text("executor"),
    workerName: text("worker_name"),
    backendStopReason: text("backend_stop_reason"),
    errorCode: text("error_code"),
  };
  return Object.fromEntries(
    Object.entries(identity).filter(([, item]) => item !== undefined),
  ) as Partial<typeof identity>;
}

/** A new execution must never pick up an older execution's persisted steps. */
export function matchesExecution(
  expected: { executionId?: string; dispatchId?: string },
  event: Record<string, unknown>,
): boolean {
  if (expected.executionId) return event.execution_id === expected.executionId;
  if (expected.dispatchId) return event.dispatch_id === expected.dispatchId;
  return true;
}

export function externalUsage(
  value: unknown,
): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}
