export type SkillTier = "core-industrial" | "foundation";

export interface Skill {
  name: string;
  description: string;
  category: string;
  license: string;
  enabled: boolean;
  tier: SkillTier;
}
