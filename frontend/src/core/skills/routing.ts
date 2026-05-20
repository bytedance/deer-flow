export const SKILL_ROUTE_CATEGORIES = [
  "programming",
  "data_analysis",
  "ppt_generation",
  "image_generation",
] as const;

export type SkillRouteCategory = (typeof SKILL_ROUTE_CATEGORIES)[number];

export type SkillCategoryBindings = Partial<
  Record<SkillRouteCategory | string, string[]>
>;

export function getSkillRouteCategoryLabel(
  category: string,
  labels?: Partial<Record<SkillRouteCategory, string>>,
): string {
  if (category === "programming") {
    return labels?.programming ?? "Programming";
  }
  if (category === "data_analysis") {
    return labels?.data_analysis ?? "Data analysis";
  }
  if (category === "ppt_generation") {
    return labels?.ppt_generation ?? "PPT";
  }
  if (category === "image_generation") {
    return labels?.image_generation ?? "Image";
  }
  return category;
}
