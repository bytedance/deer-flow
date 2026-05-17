import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import AlarmBlock from "@/components/genui/AlarmBlock";
import GaugeBlock from "@/components/genui/GaugeBlock";
import MetricBlock from "@/components/genui/MetricBlock";
import StatusBlock from "@/components/genui/StatusBlock";
import { sanitizeProps } from "@/core/genui/sanitizer";
import { validateProps } from "@/core/genui/validator";

type AnyBlock = React.ComponentType<{
  block: { props: Record<string, unknown> };
}>;

const blocks: Record<string, AnyBlock> = {
  GaugeBlock: GaugeBlock as unknown as AnyBlock,
  AlarmBlock: AlarmBlock as unknown as AnyBlock,
  MetricBlock: MetricBlock as unknown as AnyBlock,
  StatusBlock: StatusBlock as unknown as AnyBlock,
};

function load(name: keyof typeof blocks) {
  return blocks[name]!;
}

// ─── GaugeBlock ─────────────────────────────────────────────────────

describe("GaugeBlock", () => {
  it("validates a minimal gauge", () => {
    expect(validateProps("gauge", { value: 4.8 }).success).toBe(true);
  });

  it("validates with thresholds + unit + label", () => {
    const result = validateProps("gauge", {
      value: 4.8,
      min: 0,
      max: 10,
      unit: "mm/s",
      label: "P-101A 振动有效值",
      thresholds: { warn: 4.5, error: 7.1, critical: 9.0 },
    });
    expect(result.success).toBe(true);
  });

  it("rejects non-numeric value", () => {
    const result = validateProps("gauge", { value: "high" });
    expect(result.success).toBe(false);
  });

  it("renders the value with the supplied unit", async () => {
    const Gauge = load("GaugeBlock");
    const html = renderToStaticMarkup(
      React.createElement(Gauge, {
        block: { props: { value: 4.8, unit: "mm/s", label: "P-101A" } },
      }),
    );
    expect(html).toContain("4.80");
    expect(html).toContain("mm/s");
    expect(html).toContain("P-101A");
  });

  it("clamps the arc fill to the [min, max] range", async () => {
    const Gauge = load("GaugeBlock");
    const html = renderToStaticMarkup(
      React.createElement(Gauge, {
        block: { props: { value: 999, min: 0, max: 10 } },
      }),
    );
    // strokeDashoffset must end up at 0 (full fill) when over max.
    expect(html).toMatch(/stroke-dashoffset=\"0\"/);
  });
});

// ─── AlarmBlock ─────────────────────────────────────────────────────

describe("AlarmBlock", () => {
  it("validates a list of alarms", () => {
    const result = validateProps("alarm", {
      title: "P-101A 当前报警",
      items: [
        {
          level: "high",
          message: "轴承温度超阈",
          tag: "TI-101A-B1",
          time: "2026-05-17 09:14:00",
        },
        { level: "journal", message: "操作员确认报警" },
      ],
    });
    expect(result.success).toBe(true);
  });

  it("rejects unknown alarm level", () => {
    const result = validateProps("alarm", {
      items: [{ level: "fatal", message: "x" }],
    });
    expect(result.success).toBe(false);
  });

  it("renders the empty state when items is []", async () => {
    const Alarm = load("AlarmBlock");
    const html = renderToStaticMarkup(
      React.createElement(Alarm, { block: { props: { items: [] } } }),
    );
    expect(html).toContain("无报警");
  });

  it("renders priority label and tag for each item", async () => {
    const Alarm = load("AlarmBlock");
    const html = renderToStaticMarkup(
      React.createElement(Alarm, {
        block: {
          props: {
            items: [{ level: "critical", message: "压缩机喘振", tag: "K-301" }],
          },
        },
      }),
    );
    expect(html).toContain("紧急");
    expect(html).toContain("K-301");
    expect(html).toContain("压缩机喘振");
  });
});

// ─── MetricBlock ────────────────────────────────────────────────────

describe("MetricBlock", () => {
  it("validates a numeric metric with range and delta", () => {
    const result = validateProps("metric", {
      tag: "FI-101",
      label: "进料流量",
      value: 128.4,
      unit: "t/h",
      precision: 1,
      setpoint: 130,
      range: { ll: 100, l: 110, h: 145, hh: 155 },
      delta: { value: "-1.2", direction: "down", vs: "上一周期" },
    });
    expect(result.success).toBe(true);
  });

  it("accepts a string value (e.g. 'N/A')", () => {
    const result = validateProps("metric", { value: "N/A" });
    expect(result.success).toBe(true);
  });

  it("renders tag + value + unit", async () => {
    const Metric = load("MetricBlock");
    const html = renderToStaticMarkup(
      React.createElement(Metric, {
        block: {
          props: {
            tag: "TI-101A",
            value: 78.6,
            unit: "°C",
            precision: 1,
          },
        },
      }),
    );
    expect(html).toContain("TI-101A");
    expect(html).toContain("78.6");
    expect(html).toContain("°C");
  });
});

// ─── StatusBlock ────────────────────────────────────────────────────

describe("StatusBlock", () => {
  it("validates each canonical status", () => {
    for (const status of [
      "running",
      "stopped",
      "maint",
      "standby",
      "fault",
      "comm-loss",
    ]) {
      expect(validateProps("status", { status }).success).toBe(true);
    }
  });

  it("rejects unknown status kind", () => {
    expect(validateProps("status", { status: "exploded" }).success).toBe(false);
  });

  it("renders the localized label for the status", async () => {
    const Status = load("StatusBlock");
    const html = renderToStaticMarkup(
      React.createElement(Status, {
        block: { props: { status: "running", tag: "P-101A" } },
      }),
    );
    expect(html).toContain("运行");
    expect(html).toContain("P-101A");
  });
});

// ─── Sanitizer whitelist ────────────────────────────────────────────

describe("sanitizer whitelist", () => {
  it("strips disallowed keys from gauge props", () => {
    const sanitized = sanitizeProps("gauge", {
      value: 1,
      malicious: "<script>alert(1)</script>",
    });
    expect(sanitized).not.toHaveProperty("malicious");
    expect(sanitized.value).toBe(1);
  });

  it("strips disallowed keys from alarm props", () => {
    const sanitized = sanitizeProps("alarm", {
      title: "T",
      items: [],
      onAck: () => undefined,
    });
    expect(sanitized).not.toHaveProperty("onAck");
  });

  it("returns empty object for unknown component", () => {
    const sanitized = sanitizeProps("not-a-block", { foo: "bar" });
    expect(sanitized).toEqual({});
  });
});
