import { describe, it, expect } from "vitest";

import {
  ISO_VIBRATION_LEVELS,
  generateISOVibrationMarkLines,
  EQUIPMENT_STATUS_THRESHOLDS,
  generateOperatingStatusMarkAreas,
} from "@/lib/industrial-chart-annotations";

describe("ISO Vibration Levels", () => {
  it("should define four ISO zones", () => {
    expect(ISO_VIBRATION_LEVELS).toHaveLength(4);
  });

  it("should have Zone A as the lowest threshold", () => {
    const zoneA = ISO_VIBRATION_LEVELS[0];
    expect(zoneA?.label).toBe("ISO Zone A");
    expect(zoneA?.threshold).toBe(1.8);
    expect(zoneA?.color).toBe("#10b981"); // green
  });

  it("should have Zone D as the highest threshold", () => {
    const zoneD = ISO_VIBRATION_LEVELS[3];
    expect(zoneD?.label).toBe("ISO Zone D");
    expect(zoneD?.threshold).toBe(18.0);
    expect(zoneD?.color).toBe("#ef4444"); // red
  });

  it("should have thresholds in ascending order", () => {
    for (let i = 1; i < ISO_VIBRATION_LEVELS.length; i++) {
      expect(ISO_VIBRATION_LEVELS[i]!.threshold).toBeGreaterThan(
        ISO_VIBRATION_LEVELS[i - 1]!.threshold,
      );
    }
  });
});

describe("generateISOVibrationMarkLines", () => {
  it("should generate mark lines for all ISO zones", () => {
    const markLines = generateISOVibrationMarkLines();
    expect(markLines).toHaveLength(4);
  });

  it("should include yAxis threshold values", () => {
    const markLines = generateISOVibrationMarkLines();
    expect(markLines[0]!.yAxis).toBe(1.8);
    expect(markLines[3]!.yAxis).toBe(18.0);
  });

  it("should include dashed line styles", () => {
    const markLines = generateISOVibrationMarkLines();
    markLines.forEach((line) => {
      expect(line.lineStyle.type).toBe("dashed");
      expect(line.lineStyle.width).toBe(1.5);
    });
  });

  it("should include zone labels", () => {
    const markLines = generateISOVibrationMarkLines();
    expect(markLines[0]!.label.formatter).toBe("ISO Zone A");
    expect(markLines[1]!.label.formatter).toBe("ISO Zone B");
  });
});

describe("Equipment Status Thresholds", () => {
  it("should define thresholds for common metrics", () => {
    expect(EQUIPMENT_STATUS_THRESHOLDS.temperature).toBeDefined();
    expect(EQUIPMENT_STATUS_THRESHOLDS.pressure).toBeDefined();
    expect(EQUIPMENT_STATUS_THRESHOLDS.vibration).toBeDefined();
    expect(EQUIPMENT_STATUS_THRESHOLDS.bearingTemp).toBeDefined();
  });

  it("should have temperature thresholds in ascending order", () => {
    const temp = EQUIPMENT_STATUS_THRESHOLDS.temperature;
    expect(temp.normal).toBeLessThan(temp.warning);
    expect(temp.warning).toBeLessThan(temp.alarm);
  });

  it("should include units for all metrics", () => {
    Object.values(EQUIPMENT_STATUS_THRESHOLDS).forEach((threshold) => {
      expect(threshold.unit).toBeDefined();
      expect(typeof threshold.unit).toBe("string");
    });
  });
});

describe("generateOperatingStatusMarkAreas", () => {
  it("should generate three mark areas for each metric", () => {
    const areas = generateOperatingStatusMarkAreas("temperature");
    expect(areas).toHaveLength(3);
  });

  it("should create zones from 0 to normal, normal to warning, warning to alarm", () => {
    const areas = generateOperatingStatusMarkAreas("temperature");
    expect(areas[0]![0].yAxis).toBe(0);
    expect(areas[0]![1].yAxis).toBe(65); // normal
    expect(areas[1]![0].yAxis).toBe(65); // normal
    expect(areas[1]![1].yAxis).toBe(85); // warning
    expect(areas[2]![0].yAxis).toBe(85); // warning
    expect(areas[2]![1].yAxis).toBe(95); // alarm
  });

  it("should apply color coding to zones", () => {
    const areas = generateOperatingStatusMarkAreas("vibration");
    expect(areas[0]![0].itemStyle?.color).toContain("16, 185, 129"); // green
    expect(areas[1]![0].itemStyle?.color).toContain("245, 158, 11"); // yellow
    expect(areas[2]![0].itemStyle?.color).toContain("239, 68, 68"); // red
  });

  it("should work for all supported metrics", () => {
    const metrics = ["temperature", "pressure", "vibration", "bearingTemp"] as const;
    metrics.forEach((metric) => {
      const areas = generateOperatingStatusMarkAreas(metric);
      expect(areas).toHaveLength(3);
    });
  });
});
