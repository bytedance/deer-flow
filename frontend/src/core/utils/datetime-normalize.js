export function normalizeDateForTimeAgo(value) {
  if (typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value)) {
    return new Date(Number(value) * 1000);
  }

  return value;
}
