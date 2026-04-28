export type GlobalVariable = {
  key: string;
  value: string;
  description: string;
  is_system: boolean;
  llm_editable: boolean;
  updated_at: string;
  updated_by: string;
};

export type VariableFormData = {
  key: string;
  value: string;
  description: string;
  llm_editable: boolean;
  is_system: boolean;
};

export type VariableScope = "project" | "thread";
