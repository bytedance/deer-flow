import { afterEach, describe, expect, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { I18nProvider } from "@/core/i18n/context";

afterEach(cleanup);

describe("ScheduledTaskScheduleInput", () => {
  async function selectPreset(name: string) {
    fireEvent.keyDown(screen.getByTestId("schedule-preset"), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("option", { name }));
  }

  function renderCron(cron: string) {
    const emitted: ScheduleValue[] = [];
    render(
      <I18nProvider initialLocale="en-US">
        <ScheduledTaskScheduleInput
          initial={{
            schedule_type: "cron",
            schedule_spec: { cron },
            timezone: "UTC",
          }}
          onChange={(value) => emitted.push(value)}
        />
      </I18nProvider>,
    );
    return emitted;
  }

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
