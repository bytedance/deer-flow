import { afterEach, describe, expect, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { I18nProvider } from "@/core/i18n/context";

afterEach(cleanup);

describe("ScheduledTaskScheduleInput", () => {
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
