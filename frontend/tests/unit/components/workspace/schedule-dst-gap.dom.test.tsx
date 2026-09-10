import { afterEach, expect, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { I18nProvider } from "@/core/i18n/context";

afterEach(() => {
  cleanup();
  document.cookie = "locale=; max-age=0; path=/";
});

test.each([
  ["en-US", "This local time does not exist"],
  ["zh-CN", "所选时区中不存在这个本地时间"],
] as const)(
  "invalid wall time clears the spec and recovers in %s",
  (locale, message) => {
    document.cookie = `locale=${locale}; path=/`;
    const emitted: ScheduleValue[] = [];
    const { container } = render(
      <I18nProvider initialLocale={locale}>
        <ScheduledTaskScheduleInput
          initial={{
            schedule_type: "once",
            schedule_spec: { run_at: "2027-03-14T06:30:00Z" },
            timezone: "America/New_York",
          }}
          onChange={(value) => emitted.push(value)}
        />
      </I18nProvider>,
    );
    const input = container.querySelector<HTMLInputElement>(
      'input[type="datetime-local"]',
    )!;
    expect(input.value).toBe("2027-03-14T01:30");
    expect(emitted.at(-1)?.schedule_spec.run_at).toBe(
      "2027-03-14T06:30:00+00:00",
    );
    fireEvent.change(input, { target: { value: "2027-03-14T02:30" } });
    expect(screen.getByRole("alert").textContent).toContain(message);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(emitted.at(-1)?.schedule_spec).toEqual({});
    expect(Object.keys(emitted.at(-1)!)).toEqual([
      "schedule_type",
      "schedule_spec",
      "timezone",
    ]);
    fireEvent.change(input, { target: { value: "2027-03-14T03:30" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(emitted.at(-1)?.schedule_spec.run_at).toBe(
      "2027-03-14T07:30:00+00:00",
    );
    fireEvent.change(input, { target: { value: "" } });
    expect(emitted.at(-1)?.schedule_spec).toEqual({});
  },
);
