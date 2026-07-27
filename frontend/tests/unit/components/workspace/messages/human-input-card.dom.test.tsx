import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { HumanInputCard } from "@/components/workspace/messages/human-input-card";
import { I18nContext } from "@/core/i18n/context";
import type { HumanInputRequest } from "@/core/messages/human-input";

const formRequest: HumanInputRequest = {
  version: 2,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:call-form",
  question: "Please provide the expense details.",
  input_mode: "form",
  fields: [
    { name: "amount", label: "Amount", type: "number", required: true },
    { name: "category", label: "Category", type: "text", required: true },
  ],
};

function renderCard() {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined }}
    >
      <HumanInputCard request={formRequest} onSubmit={() => undefined} />
    </I18nContext.Provider>,
  );
}

afterEach(cleanup);
afterEach(() => {
  rs.restoreAllMocks();
});

describe("HumanInputCard form validation (DOM)", () => {
  it("keeps the error node mounted while another field is still invalid", () => {
    renderCard();

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    // Both required fields flagged; the error node exists and is referenced.
    const amount = screen.getByLabelText(/Amount/);
    const category = screen.getByLabelText(/Category/);
    expect(amount.getAttribute("aria-invalid")).toBe("true");
    expect(category.getAttribute("aria-invalid")).toBe("true");
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("required fields");

    // Fixing ONE field must not unmount the error node the other field's
    // aria-describedby still points at.
    fireEvent.change(amount, { target: { value: "300" } });
    expect(amount.getAttribute("aria-invalid")).toBeNull();
    expect(category.getAttribute("aria-invalid")).toBe("true");
    const describedBy = category.getAttribute("aria-describedby");
    expect(describedBy).not.toBeNull();
    expect(document.getElementById(describedBy!)).not.toBeNull();

    // Fixing the last invalid field clears the error entirely.
    fireEvent.change(category, { target: { value: "travel" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps select fields controlled from placeholder through selection", () => {
    const warnSpy = rs.spyOn(console, "warn").mockImplementation(() => ({}));
    render(
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined }}
      >
        <HumanInputCard
          request={{
            ...formRequest,
            fields: [
              {
                name: "category",
                label: "Category",
                type: "select",
                required: true,
                options: [
                  { id: "category-travel", label: "travel", value: "travel" },
                  { id: "category-meals", label: "meals", value: "meals" },
                ],
              },
            ],
          }}
          onSubmit={() => undefined}
        />
      </I18nContext.Provider>,
    );

    const trigger = screen.getByRole("combobox", {
      name: "Category required",
    });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: "travel" }));

    expect(
      warnSpy.mock.calls.some(([message]) =>
        String(message).includes("uncontrolled to controlled"),
      ),
    ).toBe(false);
  });
});
