import { expect, it, rs } from "@rstest/core";

import WorkspacePage from "@/app/workspace/page";

rs.mock("next/navigation", () => ({
  redirect: (href: string) => {
    throw new Error("redirect:" + href);
  },
}));
rs.mock("@/env", () => ({ env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" } }));
it("preserves selected and invalid repeated workspace locators through the native workspace entry redirect", async () => {
  const T = "22222222-2222-2222-2222-222222222222";
  for (const [selectors, suffix] of [
    [T, `?workspace_id=${T}`],
    [[T, T], `?workspace_id=${T}&workspace_id=${T}`],
    ["", "?workspace_id="],
    [undefined, ""],
  ] as const) {
    const searchParams = Promise.resolve({
      workspace_id: selectors as string | string[] | undefined,
    });
    await expect(
      Promise.resolve().then(() => WorkspacePage({ searchParams })),
    ).rejects.toThrow("redirect:/workspace/chats/new" + suffix);
  }
});
