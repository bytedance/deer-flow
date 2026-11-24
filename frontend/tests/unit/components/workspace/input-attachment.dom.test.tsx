import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  PromptInputProvider,
  usePromptInputAttachments,
} from "@/components/ai-elements/prompt-input";
import { InputAttachment } from "@/components/workspace/input-attachment";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

test("localized remove actions identify the file and preserve other attachments without submitting", () => {
  const revoke = rs.spyOn(URL, "revokeObjectURL");
  rs.spyOn(URL, "createObjectURL").mockImplementation(
    (blob) => `blob:${(blob as File).name}`,
  );
  const submit = rs.fn();
  const name = "quarterly-budget-and-project-delivery-review-final.xlsx";
  function Files() {
    const attachments = usePromptInputAttachments();
    return (
      <form onSubmit={submit}>
        <button
          type="button"
          onClick={() =>
            attachments.add([
              new File(["budget"], name),
              new File(["notes"], "notes.txt"),
            ])
          }
        >
          Add
        </button>
        {attachments.files.map((data) => (
          <InputAttachment key={data.id} data={data} />
        ))}
      </form>
    );
  }
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <PromptInputProvider>
        <Files />
      </PromptInputProvider>
    </I18nContext.Provider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(screen.getByTitle(name).textContent).toBe(name);
  expect(screen.getByText("Excel · 6 B")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: `移除附件：${name}` }));
  expect(screen.queryByTitle(name)).toBeNull();
  expect(
    screen.getByRole("button", { name: "移除附件：notes.txt" }),
  ).toBeTruthy();
  expect(revoke).toHaveBeenCalledWith(`blob:${name}`);
  expect(submit).not.toHaveBeenCalled();
});
