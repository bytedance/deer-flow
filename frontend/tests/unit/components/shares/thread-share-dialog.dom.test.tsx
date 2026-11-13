import { afterEach, expect, rs, test } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace/chats",
}));

import { ThreadShareDialog } from "@/components/workspace/thread-share-dialog";
import { AuthProvider, type User } from "@/core/auth/AuthProvider";
import { I18nProvider } from "@/core/i18n/context";

const user = {
  id: "owner",
  email: "owner@example.test",
  system_role: "admin",
} as User;
const link = {
  share_id: "one",
  checkpoint_id: "cp",
  seq: 1,
  created_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 86400000).toISOString(),
  revoked_at: null,
  token: "s".repeat(43),
};
function dialog(threadId: string, open = true) {
  return (
    <I18nProvider initialLocale="en-US">
      <AuthProvider initialUser={user}>
        <ThreadShareDialog
          threadId={threadId}
          open={open}
          onOpenChange={rs.fn()}
        />
      </AuthProvider>
    </I18nProvider>
  );
}
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

test("changing the selected conversation aborts a create and discards its late result", async () => {
  let finish: ((response: Response) => void) | undefined;
  let createSignal: AbortSignal | null | undefined;
  rs.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    if (init?.method === "POST") {
      createSignal = init.signal;
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    }
    return new Response("[]");
  });
  const view = render(dialog("first"));
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Create snapshot link" })
        .getAttribute("disabled"),
    ).toBeNull(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Create snapshot link" }));
  await waitFor(() => expect(createSignal).toBeDefined());
  view.rerender(dialog("second"));
  expect(createSignal?.aborted).toBe(true);
  await act(async () => {
    finish?.(new Response(JSON.stringify(link)));
  });
  expect(screen.queryByLabelText("Share link")).toBeNull();
  await waitFor(() =>
    expect(screen.getByText("No share links yet.")).toBeDefined(),
  );
});

test("closing the dialog aborts its pending list request", async () => {
  let listSignal: AbortSignal | null | undefined;
  rs.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    listSignal = init?.signal;
    return new Promise<Response>(() => {
      /* The request remains pending until unmount. */
    });
  });
  const view = render(dialog("first"));
  await waitFor(() => expect(listSignal).toBeDefined());
  view.rerender(dialog("first", false));
  expect(listSignal?.aborted).toBe(true);
});

test("an expired link can be revoked to remove the stored snapshot", async () => {
  const deleted: string[] = [];
  const expired = { ...link, expires_at: "2000-01-01T00:00:00Z" };
  rs.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    if (init?.method === "DELETE") {
      deleted.push(url instanceof Request ? url.url : url.toString());
      return new Response(null, { status: 204 });
    }
    return Response.json([expired]);
  });
  render(dialog("first"));
  await screen.findByText("Expired");
  fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
  await screen.findByText("Revoked");
  expect(deleted).toHaveLength(1);
  expect(deleted[0]).toContain("/api/threads/first/shares/one");
  expect(screen.queryByRole("button", { name: "Revoke" })).toBeNull();
});
