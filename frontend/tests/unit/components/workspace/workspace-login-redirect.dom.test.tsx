import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { WorkspaceLoginRedirect } from "@/components/workspace/workspace-login-redirect";

const push = rs.fn();
const replace = rs.fn();
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

afterEach(() => {
  cleanup();
  push.mockReset();
  replace.mockReset();
});

test("sends the visitor to login with the page they opened as next", () => {
  window.history.replaceState({}, "", "/workspace/scheduled-tasks?task_id=t-1");

  const { container } = render(<WorkspaceLoginRedirect />);

  expect(replace).toHaveBeenCalledTimes(1);
  expect(replace).toHaveBeenCalledWith(
    "/login?next=%2Fworkspace%2Fscheduled-tasks%3Ftask_id%3Dt-1",
  );
  // A replace, so Back does not return to this empty page.
  expect(push).not.toHaveBeenCalled();
  expect(container.innerHTML).toBe("");
});

test("keeps the fragment, so an anchored deep link survives the round trip", () => {
  window.history.replaceState(
    {},
    "",
    "/workspace/chats/thread-1?x=1#message-3",
  );

  render(<WorkspaceLoginRedirect />);

  expect(replace).toHaveBeenCalledWith(
    "/login?next=%2Fworkspace%2Fchats%2Fthread-1%3Fx%3D1%23message-3",
  );
});
