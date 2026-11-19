import { expect, rs, test } from "@rstest/core";
import { renderToString } from "react-dom/server";

import { useLocalSettings } from "@/core/settings/hooks";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";

const mocks = rs.hoisted(() => ({ start: rs.fn() }));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "alice" } }),
}));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/settings/user-preferences", () => ({
  startUserPreferences: mocks.start,
}));

function Workspace() {
  const [settings] = useLocalSettings();
  return (
    <main>
      <nav>Workspace sidebar</nav>
      <output>{settings.context.model_name ?? "default"}</output>
    </main>
  );
}

test("signed-in workspace content remains in server HTML without starting browser sync", () => {
  const html = renderToString(
    <UserPreferencesBoundary>
      <Workspace />
    </UserPreferencesBoundary>,
  );
  expect(html).toContain("<nav>Workspace sidebar</nav>");
  expect(html).toContain("<output>default</output>");
  expect(mocks.start).not.toHaveBeenCalled();
});
