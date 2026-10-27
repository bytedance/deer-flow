// The workspace owns layout and lifecycle; each available module owns its UI.
// A planned module has no factory and cannot call backend actions.
export function createEvolutionModules(factories) {
  return [
    {
      id: "skill",
      label: { en: "Skill evolution", zh: "Skill 自演进" },
      description: { en: "Turn usage feedback into better skills.", zh: "从使用反馈中持续改进技能。" },
      state: "available",
      create: factories.skill,
    },
    {
      id: "memory",
      label: { en: "Memory evolution", zh: "Memory 自演进" },
      description: { en: "Reserved for future memory improvements.", zh: "记忆优化能力，后续开放。" },
      state: "planned",
    },
  ];
}
