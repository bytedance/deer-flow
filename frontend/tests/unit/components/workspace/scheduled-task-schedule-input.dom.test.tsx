import { afterEach, describe, expect, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { I18nProvider } from "@/core/i18n/context";

afterEach(cleanup);

describe("ScheduledTaskScheduleInput", () => {
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

  test.each([
    ["weekly", "30 14 * * 1,3,5"],
    ["monthly", "30 14 21 * *"],
    ["hourly", "30 * * * *"],
    ["daily", "30 14 * * *"],
  ])(
    "switching to custom from a %s task preserves its schedule",
    (_preset, cron) => {
      const { emitted } = renderCronInput(cron);

      switchPreset("Custom cron");

      const cronInput = screen.getByTestId<HTMLInputElement>("schedule-cron");
      expect(cronInput.value).toBe(cron);
      expect(emitted.at(-1)?.schedule_spec.cron).toBe(cron);
    },
  );

  test("returning to custom reflects the edited weekly schedule, not the stale expression", () => {
    const { emitted, container } = renderCronInput("*/10 * * * *");

    switchPreset("Weekly");
    const timeInput =
      container.querySelector<HTMLInputElement>('input[type="time"]')!;
    fireEvent.change(timeInput, { target: { value: "14:30" } });

    switchPreset("Custom cron");
    const cronInput = screen.getByTestId<HTMLInputElement>("schedule-cron");
    expect(cronInput.value).toBe("30 14 * * 1");
    expect(emitted.at(-1)?.schedule_spec.cron).toBe("30 14 * * 1");
  });
});

function renderCronInput(cron: string): {
  emitted: ScheduleValue[];
  container: HTMLElement;
} {
  const emitted: ScheduleValue[] = [];
  const { container } = render(
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
  return { emitted, container };
}

function switchPreset(name: string) {
  fireEvent.keyDown(screen.getByTestId("schedule-preset"), {
    key: "ArrowDown",
  });
  fireEvent.click(screen.getByRole("option", { name }));
}
