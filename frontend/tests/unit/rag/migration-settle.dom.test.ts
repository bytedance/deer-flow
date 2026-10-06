import { expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import type { RagMigrationStatus } from "@/core/rag/types";

/**
 * 迁移落地 ⇒ 重读生效配置（spec 2026-09-26 D5-7 的前端半边）。
 *
 * 在飞期间 `config.embedding_dimension` 仍是旧宽度（服务端按设计如此），表单也显示"正在迁移
 * 到的那个值"；只有落地那一刻（成功则真的换了、失败则没换）重读一次，界面才会回到真实状态。
 * 不重读的两个后果都真发生过：成功后表单停在目标值而无从核对，失败后表单停在一个并不生效的值。
 */
const apiMock = rs.hoisted(() => ({
  loadRagMigrationStatus: rs.fn(),
}));
rs.mock("@/core/rag/api", () => apiMock);

const { useRagMigrationStatus } = await import("@/core/rag/hooks");

function status(state: RagMigrationStatus["state"]): RagMigrationStatus {
  return { state, target_dimension: 1536, detail: null, progress: null };
}

/**
 * ``setup`` returns the mutable verdict the stubbed endpoint answers with: the hook must be
 * able to *move* from running to settled inside one mount, which a once-only stub cannot do
 * (`mockResolvedValue` does not replace an already-set implementation under this runner).
 */
function setup(initial: RagMigrationStatus["state"]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const invalidate = rs.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  let next = status(initial);
  apiMock.loadRagMigrationStatus.mockImplementation(async () => next);
  return {
    invalidate,
    wrapper,
    answer: (state: RagMigrationStatus["state"]) => {
      next = status(state);
    },
  };
}

test("re-reads the live configuration once a migration settles", async () => {
  const { invalidate, wrapper, answer } = setup("running");

  const { result } = renderHook(() => useRagMigrationStatus(), { wrapper });
  await waitFor(() => expect(result.current.data?.state).toBe("running"));
  expect(invalidate).not.toHaveBeenCalled();

  // 不手摇 refetch：这个 hook 在飞时本来就每 3s 轮询一次，走真实的那条路。
  answer("succeeded");
  await waitFor(() => expect(result.current.data?.state).toBe("succeeded"), {
    timeout: 8000,
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ragConfig"] });
});

test("a failed migration also re-reads — the width it shows must be the one in force", async () => {
  const { invalidate, wrapper, answer } = setup("running");

  const { result } = renderHook(() => useRagMigrationStatus(), { wrapper });
  await waitFor(() => expect(result.current.data?.state).toBe("running"));

  answer("failed");
  await waitFor(() => expect(result.current.data?.state).toBe("failed"), {
    timeout: 8000,
  });

  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ragConfig"] });
});

test("never re-reads on a mount that only ever saw a settled verdict", async () => {
  const { invalidate, wrapper } = setup("succeeded");

  const { result } = renderHook(() => useRagMigrationStatus(), { wrapper });
  await waitFor(() => expect(result.current.data?.state).toBe("succeeded"));
  await new Promise((resolve) => setTimeout(resolve, 3500));

  expect(invalidate).not.toHaveBeenCalled();
});
