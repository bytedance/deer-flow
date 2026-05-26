"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import yaml from "js-yaml";

export interface FormField {
  name: string;
  type: string;
  label: string;
  required?: boolean;
  default?: unknown;
  placeholder?: string;
  description?: string;
  options?: { label: string; value: string }[];
}

export interface FormStep {
  id: string;
  title: string;
  fields: FormField[];
  next?: string;
  before_step?: {
    script: string;
    args?: Record<string, unknown>;
  };
}

export interface DataStep {
  id: string;
  script: string;
  args?: Record<string, unknown>;
  outputs?: Record<string, string>;
}

export interface Transform {
  id: string;
  script: string;
  input?: string;
  args?: Record<string, unknown>;
  outputs?: Record<string, string>;
}

export interface Section {
  id: string;
  title: string;
  component: string;
  source?: string;
  config?: Record<string, unknown>;
}

export interface ReportTemplateDSL {
  name: string;
  display_name?: string;
  description?: string;
  form_steps?: FormStep[];
  data_steps?: DataStep[];
  transforms?: Transform[];
  sections?: Section[];
  export?: {
    formats?: string[];
    options?: Record<string, unknown>;
  };
}

export interface UseTemplateDSLReturn {
  dsl: ReportTemplateDSL;
  dslYaml: string;
  isDirty: boolean;
  updateDSL: (updater: (prev: ReportTemplateDSL) => ReportTemplateDSL) => void;
  setDSL: (newDSL: ReportTemplateDSL) => void;
  loadFromYaml: (yamlStr: string) => void;
  markClean: () => void;
  // Convenience updaters
  updateFormSteps: (
    updater: (prev: FormStep[]) => FormStep[],
  ) => void;
  updateDataSteps: (
    updater: (prev: DataStep[]) => DataStep[],
  ) => void;
  updateTransforms: (
    updater: (prev: Transform[]) => Transform[],
  ) => void;
  updateSections: (
    updater: (prev: Section[]) => Section[],
  ) => void;
}

const DEFAULT_DSL: ReportTemplateDSL = {
  name: "new-template",
  display_name: "New Template",
  description: "",
  form_steps: [],
  data_steps: [],
  transforms: [],
  sections: [],
};

function dslToYaml(dsl: ReportTemplateDSL): string {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(dsl)) {
    if (value !== undefined && value !== null && value !== "") {
      if (Array.isArray(value) && value.length === 0) continue;
      clean[key] = value;
    }
  }
  return yaml.dump(clean, { lineWidth: 120, noRefs: true });
}

function yamlToDSL(yamlStr: string): ReportTemplateDSL {
  const parsed = yaml.load(yamlStr) as Record<string, unknown>;
  if (!parsed || typeof parsed !== "object") {
    return { ...DEFAULT_DSL };
  }
  return {
    ...DEFAULT_DSL,
    ...parsed,
  } as ReportTemplateDSL;
}

export function useTemplateDSL(
  initialDSL?: ReportTemplateDSL,
): UseTemplateDSLReturn {
  const [dsl, setDSLState] = useState<ReportTemplateDSL>(
    () => initialDSL ?? { ...DEFAULT_DSL },
  );
  const [dslYaml, setDslYaml] = useState(() =>
    dslToYaml(initialDSL ?? DEFAULT_DSL),
  );
  const [isDirty, setIsDirty] = useState(false);
  const initialRef = useRef(JSON.stringify(initialDSL ?? DEFAULT_DSL));

  const updateDSL = useCallback(
    (updater: (prev: ReportTemplateDSL) => ReportTemplateDSL) => {
      setDSLState((prev) => {
        const next = updater(prev);
        setDslYaml(dslToYaml(next));
        setIsDirty(JSON.stringify(next) !== initialRef.current);
        return next;
      });
    },
    [],
  );

  const setDSL = useCallback((newDSL: ReportTemplateDSL) => {
    setDSLState(newDSL);
    setDslYaml(dslToYaml(newDSL));
    setIsDirty(JSON.stringify(newDSL) !== initialRef.current);
  }, []);

  const loadFromYaml = useCallback((yamlStr: string) => {
    const parsed = yamlToDSL(yamlStr);
    setDSLState(parsed);
    setDslYaml(yamlStr);
    setIsDirty(JSON.stringify(parsed) !== initialRef.current);
  }, []);

  const markClean = useCallback(() => {
    initialRef.current = JSON.stringify(dsl);
    setIsDirty(false);
  }, [dsl]);

  const updateFormSteps = useCallback(
    (updater: (prev: FormStep[]) => FormStep[]) => {
      updateDSL((prev) => ({
        ...prev,
        form_steps: updater(prev.form_steps ?? []),
      }));
    },
    [updateDSL],
  );

  const updateDataSteps = useCallback(
    (updater: (prev: DataStep[]) => DataStep[]) => {
      updateDSL((prev) => ({
        ...prev,
        data_steps: updater(prev.data_steps ?? []),
      }));
    },
    [updateDSL],
  );

  const updateTransforms = useCallback(
    (updater: (prev: Transform[]) => Transform[]) => {
      updateDSL((prev) => ({
        ...prev,
        transforms: updater(prev.transforms ?? []),
      }));
    },
    [updateDSL],
  );

  const updateSections = useCallback(
    (updater: (prev: Section[]) => Section[]) => {
      updateDSL((prev) => ({
        ...prev,
        sections: updater(prev.sections ?? []),
      }));
    },
    [updateDSL],
  );

  useEffect(() => {
    if (initialDSL) {
      setDSLState(initialDSL);
      setDslYaml(dslToYaml(initialDSL));
      initialRef.current = JSON.stringify(initialDSL);
      setIsDirty(false);
    }
  }, [initialDSL]);

  return {
    dsl,
    dslYaml,
    isDirty,
    updateDSL,
    setDSL,
    loadFromYaml,
    markClean,
    updateFormSteps,
    updateDataSteps,
    updateTransforms,
    updateSections,
  };
}
