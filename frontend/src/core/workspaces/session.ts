import { getAPIClient } from "@/core/api/api-client";
import { GatewayApiError } from "@/core/api/errors";
import { createWorkspaceRESTClient } from "@/core/api/fetcher";

import {
  readWorkspaceSelection,
  WorkspaceResponseError,
  type Workspace,
  type WorkspaceContextProjection,
} from "./api";
import {
  captureWorkspaceRequestScope,
  type WorkspaceRequestScope,
} from "./request-scope";

export interface WorkspaceLifetime {
  readonly context: WorkspaceContextProjection;
  readonly scope: WorkspaceRequestScope;
  readonly cacheKey: string;
  readonly rest: ReturnType<typeof createWorkspaceRESTClient>;
  readonly sdk: ReturnType<typeof getAPIClient>;
}
export interface WorkspaceState {
  readonly status: "loading" | "ready" | "error";
  readonly workspaces: readonly Workspace[];
  readonly active: WorkspaceLifetime | null;
  readonly error:
    | "invalid_response"
    | "authentication_required"
    | "unavailable"
    | null;
}
const EMPTY: readonly Workspace[] = Object.freeze([]);
const INITIAL: WorkspaceState = Object.freeze({
  status: "loading",
  workspaces: EMPTY,
  active: null,
  error: null,
});
export const AUTHENTICATION_REQUIRED: WorkspaceState = Object.freeze({
  status: "error",
  workspaces: EMPTY,
  active: null,
  error: "authentication_required",
});

/** One provider/tab owns this state; it never reads a global last workspace. */
export class WorkspaceSession {
  private state: WorkspaceState = INITIAL;
  private listeners = new Set<() => void>();
  private operation: AbortController | null = null;
  private epoch = 0;
  private closed = false;
  private started = false;
  private requestedSelector: string | undefined;
  private leases = 0;
  private releaseEpoch = 0;
  constructor(
    private readonly actorUserId: string,
    initialSelector?: string,
  ) {
    this.requestedSelector = initialSelector;
  }

  getSnapshot = () => this.state;
  getRequestedSelector = () => this.requestedSelector;
  getServerSnapshot = () => INITIAL;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private publish(state: WorkspaceState) {
    this.state = Object.freeze(state);
    for (const listener of this.listeners) listener();
  }

  acquire = () => {
    if (this.closed) return () => undefined;
    this.leases += 1;
    this.releaseEpoch += 1;
    if (!this.started) {
      this.started = true;
      void this.select(this.requestedSelector);
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.leases -= 1;
      const releaseEpoch = ++this.releaseEpoch;
      // StrictMode immediately reacquires the same store. A real unmount
      // closes it permanently; stale callbacks can never reopen its scope.
      queueMicrotask(() => {
        if (!this.leases && this.releaseEpoch === releaseEpoch) this.dispose();
      });
    };
  };

  select = async (selector?: string): Promise<boolean> => {
    if (this.closed) return false;
    this.started = true;
    this.requestedSelector = selector;
    this.operation?.abort();
    const operation = new AbortController();
    this.operation = operation;
    const epoch = ++this.epoch;
    this.publish({
      status: "loading",
      workspaces: this.state.workspaces,
      active: null,
      error: null,
    });
    try {
      const confirmed = await readWorkspaceSelection(
        this.actorUserId,
        selector,
        operation.signal,
      );
      if (this.closed || this.epoch !== epoch || operation.signal.aborted)
        return false;
      const scope = captureWorkspaceRequestScope({
        actorUserId: confirmed.context.actorUserId,
        workspaceId: confirmed.context.workspaceId,
        signal: operation.signal,
      });
      const active: WorkspaceLifetime = Object.freeze({
        context: confirmed.context,
        scope,
        cacheKey: JSON.stringify([
          scope.actorUserId,
          scope.workspaceId,
          confirmed.context.membershipVersion,
          confirmed.context.policyVersion,
          epoch,
        ]),
        rest: createWorkspaceRESTClient(scope),
        sdk: getAPIClient(false, scope),
      });
      this.publish({
        status: "ready",
        workspaces: confirmed.workspaces,
        active,
        error: null,
      });
      return true;
    } catch (error) {
      if (this.closed || this.epoch !== epoch || operation.signal.aborted)
        return false;
      operation.abort();
      const reason =
        error instanceof WorkspaceResponseError
          ? "invalid_response"
          : error instanceof GatewayApiError && error.status === 401
            ? "authentication_required"
            : "unavailable";
      this.publish({
        status: "error",
        workspaces: EMPTY,
        active: null,
        error: reason,
      });
      return false;
    }
  };
  refresh = () => this.select(this.requestedSelector);
  private dispose() {
    this.closed = true;
    this.epoch += 1;
    this.operation?.abort();
    this.state = Object.freeze({
      status: "error",
      workspaces: EMPTY,
      active: null,
      error: "unavailable",
    });
    this.listeners.clear();
  }
}
