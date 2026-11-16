import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { cleanup, renderHook, waitFor } from "@testing-library/react";

const nav = rs.hoisted(() => ({
  pathname: "/workspace/chats/new",
  search: "",
}));
const ids = rs.hoisted(() => ({ value: 0 }));

rs.mock("next/navigation", () => ({
  useParams: () => ({ thread_id: "new" }),
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
}));
rs.mock("@/core/utils/uuid", () => ({ uuid: () => `thread-${++ids.value}` }));

import { useThreadChat } from "@/components/workspace/chats/use-thread-chat";

function visit(search: string) {
  nav.pathname = "/workspace/chats/new";
  nav.search = search;
  window.history.replaceState(
    null,
    "",
    `/workspace/chats/new${search ? `?${search}` : ""}`,
  );
}

beforeEach(() => {
  ids.value = 0;
  visit("");
});

afterEach(cleanup);

describe("useThreadChat new-chat scope", () => {
  test("mints a fresh identity when the incognito entry toggles", async () => {
    const { result, rerender } = renderHook(() => useThreadChat());
    expect(result.current.isNewThread).toBe(true);
    const ordinaryId = result.current.threadId;

    visit("incognito=true");
    rerender();
    await waitFor(() => expect(result.current.threadId).not.toBe(ordinaryId));
    const incognitoId = result.current.threadId;
    expect(result.current.isNewThread).toBe(true);

    visit("");
    rerender();
    await waitFor(() => expect(result.current.threadId).not.toBe(incognitoId));
    expect(result.current.threadId).not.toBe(ordinaryId);
  });

  test("still mints a fresh identity when only the project scope changes", async () => {
    const { result, rerender } = renderHook(() => useThreadChat());
    const plainId = result.current.threadId;

    visit("project=p-1");
    rerender();
    await waitFor(() => expect(result.current.threadId).not.toBe(plainId));
    const projectId = result.current.threadId;

    visit("incognito=true");
    rerender();
    await waitFor(() => expect(result.current.threadId).not.toBe(projectId));
  });
});
