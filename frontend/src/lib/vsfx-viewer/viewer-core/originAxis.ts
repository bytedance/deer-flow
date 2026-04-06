export type AxisKey = "x" | "y" | "z";

export type AxisPosition = {
  coord: number;
  label?: string;
};

export type AxisPositions = Record<AxisKey, AxisPosition[]>;

export function normalizeAxisPositions(input: unknown): AxisPositions {
  const source = (input ?? {}) as Partial<Record<AxisKey, unknown>>;

  return {
    x: normalizeAxisList(source.x),
    y: normalizeAxisList(source.y),
    z: normalizeAxisList(source.z),
  };
}

function normalizeAxisList(input: unknown): AxisPosition[] {
  if (!Array.isArray(input)) {
    return [];
  }

  return input.flatMap((value) => {
    if (typeof value === "number" && Number.isFinite(value)) {
      return [{ coord: value }];
    }

    if (typeof value === "object" && value) {
      const coord = (value as { coord?: unknown }).coord;
      const label = (value as { label?: unknown }).label;

      if (typeof coord === "number" && Number.isFinite(coord)) {
        return [
          {
            coord,
            label: typeof label === "string" ? label : undefined,
          },
        ];
      }
    }

    return [];
  });
}
