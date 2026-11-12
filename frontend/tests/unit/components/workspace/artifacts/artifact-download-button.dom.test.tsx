import { afterEach, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const state = rs.hoisted(() => ({ prepare: rs.fn(), viewer: "a" }));
rs.mock("@/core/artifacts/download", () => ({
  prepareArtifactDownload: state.prepare,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: state.viewer } }),
}));

import { ArtifactDownloadButton } from "@/components/workspace/artifacts/artifact-download-button";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const component = (file = "/report.txt") => (
  <I18nContext.Provider
    value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
  >
    <ArtifactDownloadButton filepath={file} threadId="thread" />
  </I18nContext.Provider>
);
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  state.prepare.mockReset();
  state.viewer = "a";
});

it("blocks duplicate clicks while preparing, shows retry on error and downloads after retry", async () => {
  let reject!: (error: Error) => void;
  state.prepare.mockImplementationOnce(
    () =>
      new Promise((_, fail) => {
        reject = fail;
      }),
  );
  state.prepare.mockResolvedValueOnce(new Blob(["report"]));
  const create = rs
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:report");
  const click = rs
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  const revoke = rs.spyOn(URL, "revokeObjectURL");
  const view = render(component());
  const button = screen.getByRole("button", { name: "Download report.txt" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(state.prepare).toHaveBeenCalledTimes(1);
  expect(state.prepare.mock.calls[0]![0]).toContain("?download=true");
  expect(
    screen.getByRole("button", { name: /Preparing/ }).hasAttribute("disabled"),
  ).toBe(true);
  await act(async () => reject(new Error("offline")));
  fireEvent.click(screen.getByRole("button", { name: /Retry download/ }));
  // Wait for React to commit the status after the browser download is triggered.
  await waitFor(() =>
    expect(screen.getByRole("status").textContent).toBe(
      enUS.artifactPreview.downloadRequested,
    ),
  );
  expect(click).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(revoke).toHaveBeenCalledWith("blob:report");
});

it("aborts an old viewer's preparation and ignores late success", async () => {
  let resolve!: (blob: Blob) => void;
  state.prepare.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const click = rs
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  const view = render(component());
  fireEvent.click(screen.getByRole("button", { name: "Download report.txt" }));
  const signal = state.prepare.mock.calls[0]![1] as AbortSignal;
  state.viewer = "b";
  view.rerender(component());
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(new Blob(["old"])));
  expect(click).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "Download report.txt" }),
  ).toBeTruthy();
});
