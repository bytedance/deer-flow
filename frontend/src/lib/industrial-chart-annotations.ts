/**
 * ISO 10816 Vibration Severity Standards
 *
 * These thresholds define vibration velocity limits (mm/s RMS) for different
 * machine classes. Used for markLine annotations in industrial charts.
 */

export interface ISOVibrationLevel {
  label: string;
  threshold: number;
  color: string;
  description: string;
}

/**
 * ISO 10816-1: General guidelines for vibration severity
 * Applicable to machines with power > 15 kW
 */
export const ISO_VIBRATION_LEVELS: ISOVibrationLevel[] = [
  {
    label: "ISO Zone A",
    threshold: 1.8,
    color: "#10b981",
    description: "Good - Newly commissioned machines",
  },
  {
    label: "ISO Zone B",
    threshold: 4.5,
    color: "#f59e0b",
    description: "Satisfactory - Long-term acceptable",
  },
  {
    label: "ISO Zone C",
    threshold: 11.2,
    color: "#f97316",
    description: "Unsatisfactory - Limited operation",
  },
  {
    label: "ISO Zone D",
    threshold: 18.0,
    color: "#ef4444",
    description: "Severe - Danger of damage",
  },
];

/**
 * Generate ECharts markLine data for ISO vibration levels
 *
 * Usage in EChartBlock option:
 * ```js
 * series: [{
 *   type: "line",
 *   data: [...],
 *   markLine: {
 *     data: generateISOVibrationMarkLines()
 *   }
 * }]
 * ```
 */
export function generateISOVibrationMarkLines() {
  return ISO_VIBRATION_LEVELS.map((level) => ({
    yAxis: level.threshold,
    label: {
      formatter: level.label,
      position: "insideEndTop",
      fontSize: 10,
      color: level.color,
    },
    lineStyle: {
      color: level.color,
      type: "dashed",
      width: 1.5,
    },
  }));
}

/**
 * Equipment operating status intervals
 *
 * Common thresholds for industrial equipment monitoring
 */
export const EQUIPMENT_STATUS_THRESHOLDS = {
  temperature: {
    normal: 65,
    warning: 85,
    alarm: 95,
    unit: "°C",
  },
  pressure: {
    normal: 0.8,
    warning: 1.2,
    alarm: 1.5,
    unit: "MPa",
  },
  vibration: {
    normal: 4.5,
    warning: 11.2,
    alarm: 18.0,
    unit: "mm/s",
  },
  bearingTemp: {
    normal: 75,
    warning: 90,
    alarm: 100,
    unit: "°C",
  },
} as const;

/**
 * Generate markArea data for equipment operating status zones
 *
 * Creates colored background zones showing normal/warning/alarm ranges
 */
export function generateOperatingStatusMarkAreas(
  metric: keyof typeof EQUIPMENT_STATUS_THRESHOLDS,
) {
  const thresholds = EQUIPMENT_STATUS_THRESHOLDS[metric];
  return [
    [
      {
        yAxis: 0,
        itemStyle: { color: "rgba(16, 185, 129, 0.1)" },
      },
      { yAxis: thresholds.normal },
    ],
    [
      {
        yAxis: thresholds.normal,
        itemStyle: { color: "rgba(245, 158, 11, 0.1)" },
      },
      { yAxis: thresholds.warning },
    ],
    [
      {
        yAxis: thresholds.warning,
        itemStyle: { color: "rgba(239, 68, 68, 0.1)" },
      },
      { yAxis: thresholds.alarm },
    ],
  ];
}
