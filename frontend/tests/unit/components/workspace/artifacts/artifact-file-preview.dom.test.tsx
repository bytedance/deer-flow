import { afterEach, expect, rs, test } from "@rstest/core";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import { ArtifactFilePreview } from "@/components/workspace/artifacts/artifact-file-preview";
import { prepareHtmlPreview } from "@/core/artifacts/html-assets";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/artifacts/html-assets", () => ({
  prepareHtmlPreview: rs.fn(),
}));
rs.mock("@/core/streamdown/components", () => ({
  SafeStreamdown: () => null,
  toStreamdownComponents: () => ({}),
}));

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.mocked(prepareHtmlPreview).mockReset();
});

test("cancels obsolete preparation, hides previous content and releases document URLs", async () => {
  let resolveOld!: (
    result: Awaited<ReturnType<typeof prepareHtmlPreview>>,
  ) => void;
  const prepare = rs.mocked(prepareHtmlPreview);
  prepare.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
  );
  prepare.mockResolvedValue({
    content: "<h1>Current</h1>",
    failedResources: 0,
  });
  const create = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:current");
  const revoke = rs
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => undefined);
  const component = (content: string) => (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <ArtifactFilePreview
        content={content}
        language="html"
        scrollKey={content}
        url={`/api/threads/${content}/artifacts/report.html`}
      />
    </I18nContext.Provider>
  );
  const result = render(component("old"));
  const oldSignal = prepare.mock.calls[0]![2]!;
  result.rerender(component("current"));
  expect(oldSignal.aborted).toBe(true);
  await waitFor(() =>
    expect(result.container.querySelector("iframe")?.getAttribute("src")).toBe(
      "blob:current",
    ),
  );
  await act(async () => {
    resolveOld({ content: "<h1>Old</h1>", failedResources: 0 });
  });
  expect(create).toHaveBeenCalledTimes(1);
  expect(result.container.querySelector("iframe")?.getAttribute("src")).toBe(
    "blob:current",
  );
  prepare.mockImplementationOnce(() => new Promise(() => undefined));
  result.rerender(component("pending"));
  expect(result.container.querySelector("iframe")?.hasAttribute("src")).toBe(
    false,
  );
  expect(revoke).toHaveBeenCalledWith("blob:current");
  const pendingSignal = prepare.mock.calls[2]![2]!;
  result.unmount();
  expect(pendingSignal.aborted).toBe(true);
});
