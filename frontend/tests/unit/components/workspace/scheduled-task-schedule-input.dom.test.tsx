import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { useState, type ReactNode } from "react";

import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import { enUS } from "@/core/i18n/locales/en-US";
import { utcToZonedLocalInput } from "@/core/scheduled-tasks/cron";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

// Exercise schedule state with native selects; the page E2E uses real Radix UI.
rs.mock("@/components/ui/select", () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    children: ReactNode;
  }) => (
    <select
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}));

afterEach(cleanup);

function once(runAt: string, timezone = "America/New_York"): ScheduleValue {
  return { schedule_type: "once", schedule_spec: { run_at: runAt }, timezone };
}

test.each([
  "2026-11-01T06:30:00Z",
  "2027-06-01T12:30:45Z",
  "2027-06-01T12:30:45.123Z",
  "2027-06-01T08:30:00-04:00",
])("preserves the original one-time timestamp on mount: %s", (runAt) => {
  const initial = once(runAt);
  const onChange = rs.fn();
  render(
    <ScheduledTaskScheduleInput
      initial={initial}
      onChange={onChange}
      scheduleTypeLocked
    />,
  );
  expect(onChange).toHaveBeenLastCalledWith(initial);
});

test("parent feedback and title-only rerenders retain the original instant", () => {
  const original = once("2026-11-01T06:30:00Z");
  function Editor() {
    const [schedule, setSchedule] = useState(original);
    const [title, setTitle] = useState("Original");
    return (
      <>
        <input
          aria-label="Title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <ScheduledTaskScheduleInput
          initial={schedule}
          onChange={(next) => setSchedule(next)}
          scheduleTypeLocked
        />
        <output>{schedule.schedule_spec.run_at}</output>
      </>
    );
  }
  const ui = render(<Editor />);
  fireEvent.change(ui.getByLabelText("Title"), {
    target: { value: "Renamed" },
  });
  expect(ui.getByRole("status").textContent).toBe(
    original.schedule_spec.run_at,
  );
  fireEvent.change(ui.getByLabelText("Run at"), {
    target: { value: "2026-11-01T03:30" },
  });
  expect(ui.getByRole("status").textContent).toBe("2026-11-01T08:30:00+00:00");
  // Returning to the original fields must use the original snapshot, not the
  // latest value passed back through initial by the parent.
  fireEvent.change(ui.getByLabelText("Run at"), {
    target: { value: "2026-11-01T01:30" },
  });
  expect(ui.getByRole("status").textContent).toBe(
    original.schedule_spec.run_at,
  );
});

test("changing timezone recomputes the instant and reverting restores seconds", () => {
  const initial = once("2027-06-01T12:30:45Z");
  const onChange = rs.fn();
  const ui = render(
    <ScheduledTaskScheduleInput
      initial={initial}
      onChange={onChange}
      scheduleTypeLocked
    />,
  );
  fireEvent.change(ui.getByRole("combobox"), {
    target: { value: "Asia/Shanghai" },
  });
  expect(onChange).toHaveBeenLastCalledWith(
    once("2027-06-01T00:30:00+00:00", "Asia/Shanghai"),
  );
  fireEvent.change(ui.getByRole("combobox"), {
    target: { value: "America/New_York" },
  });
  expect(onChange).toHaveBeenLastCalledWith(initial);
});

test("clearing the date removes run_at", () => {
  const onChange = rs.fn();
  const ui = render(
    <ScheduledTaskScheduleInput
      initial={once("2027-06-01T12:30:45Z")}
      onChange={onChange}
      scheduleTypeLocked
    />,
  );
  fireEvent.change(ui.getByLabelText("Run at"), { target: { value: "" } });
  expect(onChange).toHaveBeenLastCalledWith({
    schedule_type: "once",
    schedule_spec: {},
    timezone: "America/New_York",
  });
});

test("empty create form converts a newly entered date", () => {
  const onChange = rs.fn();
  const ui = render(
    <ScheduledTaskScheduleInput
      initial={{
        schedule_type: "once",
        schedule_spec: {},
        timezone: "Asia/Shanghai",
      }}
      onChange={onChange}
    />,
  );
  expect(onChange).toHaveBeenLastCalledWith({
    schedule_type: "once",
    schedule_spec: {},
    timezone: "Asia/Shanghai",
  });
  fireEvent.change(ui.getByLabelText("Run at"), {
    target: { value: "2027-06-01T09:30" },
  });
  expect(onChange).toHaveBeenLastCalledWith(
    once("2027-06-01T01:30:00+00:00", "Asia/Shanghai"),
  );
});

test("switching schedule type preserves cron behavior and an unchanged once value", () => {
  const initial = once("2027-06-01T12:30:45Z");
  const onChange = rs.fn();
  const ui = render(
    <ScheduledTaskScheduleInput initial={initial} onChange={onChange} />,
  );
  fireEvent.click(ui.getByRole("button", { name: "Recurring" }));
  expect(onChange).toHaveBeenLastCalledWith({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "America/New_York",
  });
  fireEvent.click(ui.getByRole("button", { name: "One-time" }));
  expect(onChange).toHaveBeenLastCalledWith(initial);
});

test("a keyed task switch captures the next task's instant", () => {
  const onChange = rs.fn();
  const ui = render(
    <ScheduledTaskScheduleInput
      key="first"
      initial={once("2026-11-01T06:30:00Z")}
      onChange={onChange}
      scheduleTypeLocked
    />,
  );
  const next = once("2027-06-01T12:30:45Z");
  ui.rerender(
    <ScheduledTaskScheduleInput
      key="second"
      initial={next}
      onChange={onChange}
      scheduleTypeLocked
    />,
  );
  expect(onChange).toHaveBeenLastCalledWith(next);
});

test("empty timezone uses the browser zone consistently without changing the instant", () => {
  // Run this regression with TZ=Asia/Shanghai, unlike the usual UTC verifier.
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const initial = once("2026-11-01T06:30:00Z", "");
  const onChange = rs.fn();
  const ui = render(
    <ScheduledTaskScheduleInput
      initial={initial}
      onChange={onChange}
      scheduleTypeLocked
    />,
  );
  expect(onChange).toHaveBeenLastCalledWith({ ...initial, timezone });
  const expected = utcToZonedLocalInput(
    initial.schedule_spec.run_at!,
    timezone,
  );
  expect((ui.getByLabelText("Run at") as HTMLInputElement).value).toBe(
    expected,
  );
});
