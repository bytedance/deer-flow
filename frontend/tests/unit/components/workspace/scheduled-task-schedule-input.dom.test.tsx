import { afterAll, afterEach, describe, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { I18nProvider } from "@/core/i18n/context";

// The pre-fix component reads this list at module load, before any test runs.
const supportedValuesOf = rs.hoisted(() =>
  rs
    .spyOn(
      Intl as unknown as { supportedValuesOf: (key: string) => string[] },
      "supportedValuesOf",
    )
    .mockReturnValue(["America/Los_Angeles"]),
);

afterAll(() => supportedValuesOf.mockRestore());
afterEach(cleanup);

describe("ScheduledTaskScheduleInput", () => {
  async function selectPreset(name: string) {
    fireEvent.keyDown(screen.getByTestId("schedule-preset"), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("option", { name }));
  }

  function renderCron(cron: string, timezone = "UTC") {
    const emitted: ScheduleValue[] = [];
    render(
      <I18nProvider initialLocale="en-US">
        <ScheduledTaskScheduleInput
          initial={{
            schedule_type: "cron",
            schedule_spec: { cron },
            timezone,
          }}
          onChange={(value) => emitted.push(value)}
        />
      </I18nProvider>,
    );
    return emitted;
  }

  test.each(["UTC", "US/Pacific"])(
    "offers saved timezone %s when the browser's list omits it",
    async (timezone) => {
      const emitted = renderCron("0 9 * * *", timezone);
      const picker = screen.getByTestId("schedule-timezone");

      fireEvent.keyDown(picker, { key: "ArrowDown" });
      await screen.findByRole("option", { name: timezone });
      expect(screen.getAllByRole("option", { name: timezone })).toHaveLength(1);

      fireEvent.click(
        screen.getByRole("option", {
          name: "America/Los_Angeles",
        }),
      );
      expect(emitted.at(-1)?.timezone).toBe("America/Los_Angeles");

      fireEvent.keyDown(picker, { key: "ArrowDown" });
      fireEvent.click(await screen.findByRole("option", { name: timezone }));
      expect(emitted.at(-1)?.timezone).toBe(timezone);
      expect(picker.textContent).toBe(timezone);
    },
  );

  test("does not offer an invalid saved timezone", async () => {
    renderCron("0 9 * * *", "Not/AZone");

    fireEvent.keyDown(screen.getByTestId("schedule-timezone"), {
      key: "ArrowDown",
    });
    await screen.findByRole("option", {
      name: "America/Los_Angeles",
    });

    expect(screen.queryByRole("option", { name: "Not/AZone" })).toBeNull();
  });

  test.each(["15 * * * *", "30 14 * * *", "30 14 * * 1,3,5", "30 14 21 * *"])(
    "keeps %s when opening the custom cron editor",
    async (cron) => {
      const emitted = renderCron(cron);

      await selectPreset("Custom cron");

      expect(
        screen.getByRole("textbox", { name: "Cron expression" }),
      ).toHaveProperty("value", cron);
      expect(emitted.at(-1)?.schedule_spec).toEqual({ cron });
    },
  );

  test("reopening custom cron uses the current preset instead of a stale expression", async () => {
    const emitted = renderCron("*/10 * * * *");

    await selectPreset("Weekly");
    fireEvent.change(screen.getByLabelText("Time"), {
      target: { value: "16:45" },
    });
    expect(emitted.at(-1)?.schedule_spec).toEqual({ cron: "45 16 * * 1" });

    await selectPreset("Custom cron");

    expect(
      screen.getByRole("textbox", { name: "Cron expression" }),
    ).toHaveProperty("value", "45 16 * * 1");
    expect(emitted.at(-1)?.schedule_spec).toEqual({ cron: "45 16 * * 1" });

    fireEvent.change(screen.getByRole("textbox", { name: "Cron expression" }), {
      target: { value: "*/10 * * * *" },
    });
    expect(emitted.at(-1)).toEqual({
      schedule_type: "cron",
      schedule_spec: { cron: "*/10 * * * *" },
      timezone: "UTC",
    });
  });

  test.each([1, 30, 59])(
    "preserves an existing %s-second interval until explicitly edited",
    (everySeconds) => {
      const emitted: ScheduleValue[] = [];
      render(
        <I18nProvider initialLocale="en-US">
          <ScheduledTaskScheduleInput
            initial={{
              schedule_type: "interval",
              schedule_spec: { every_seconds: everySeconds },
              timezone: "UTC",
            }}
            onChange={(value) => emitted.push(value)}
          />
        </I18nProvider>,
      );

      const amountInput = screen.getByRole<HTMLInputElement>("spinbutton");
      expect(amountInput.value).toBe(String(everySeconds));
      expect(emitted.at(-1)?.schedule_spec.every_seconds).toBe(everySeconds);

      fireEvent.focus(amountInput);
      fireEvent.blur(amountInput);
      expect(amountInput.value).toBe(String(everySeconds));
      expect(emitted.at(-1)?.schedule_spec.every_seconds).toBe(everySeconds);

      fireEvent.change(amountInput, { target: { value: "9" } });
      expect(amountInput.value).toBe("9");
      expect(emitted.at(-1)?.schedule_spec.every_seconds).toBe(60);
      fireEvent.blur(amountInput);
      expect(amountInput.value).toBe("60");
    },
  );

  test("keeps interval text editable until blur applies the floor", () => {
    const emitted: ScheduleValue[] = [];

    render(
      <I18nProvider initialLocale="en-US">
        <ScheduledTaskScheduleInput
          initial={{
            schedule_type: "interval",
            schedule_spec: { every_seconds: 90 },
            timezone: "UTC",
          }}
          onChange={(value) => emitted.push(value)}
        />
      </I18nProvider>,
    );

    const amountInput = screen.getByRole("spinbutton");
    expect((amountInput as HTMLInputElement).value).toBe("90");
    expect(emitted.at(-1)?.schedule_spec.every_seconds).toBe(90);

    fireEvent.change(amountInput, { target: { value: "9" } });
    expect((amountInput as HTMLInputElement).value).toBe("9");
    expect(emitted.at(-1)?.schedule_spec.every_seconds).toBe(60);

    fireEvent.change(amountInput, { target: { value: "" } });
    expect((amountInput as HTMLInputElement).value).toBe("");
    expect(emitted.at(-1)?.schedule_spec.every_seconds).toBe(60);

    fireEvent.blur(amountInput);
    expect((amountInput as HTMLInputElement).value).toBe("60");
    expect(emitted.at(-1)?.schedule_spec.every_seconds).toBe(60);
  });
});
