export interface Skill {
  name: string;
  description: string;
  category: string;
  license: string;
  enabled: boolean;
  editable: boolean;
}

export interface SkillDetails extends Skill {
  content: string;
}
