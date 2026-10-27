import { createEvolutionModules } from "./modules.mjs";
import { zh, node, text } from "./common.mjs";
import { createSkillModule } from "./skill.mjs";

function mount(root, context) {
  const t = (en, cn) => text(context, en, cn);
  const parentSignal = context.signal;
  const controller = new AbortController();
  context = { ...context, signal: controller.signal };
  const sheet = node("link", "", {
    rel: "stylesheet",
    href: new URL("./style.css", import.meta.url).href,
  });
  const container = node("section", "", { className: "skill-evolution-status" });
  const header = node("header", "", { className: "evolution-header" });
  header.append(node("p", t("Learn from experience. Improve with every iteration.", "沉淀每一次使用反馈，让 Agent 持续成长。"), { className: "status-intro" }));
  const modulesRoot = node("div", "", { className: "evolution-modules" });
  const modules = createEvolutionModules({ skill: createSkillModule });
  const moduleInstances = new Map();
  for (const module of modules) {
    const section = node("section", "", { className: `evolution-module evolution-module-${module.state}` });
    const moduleHead = node("div", "", { className: "evolution-module-head" });
    const copy = node("div");
    copy.append(
      node("h2", zh(context) ? module.label.zh : module.label.en, { className: "evolution-module-title" }),
      node("p", zh(context) ? module.description.zh : module.description.en, { className: "status-intro" }),
    );
    moduleHead.append(copy, node("span", module.state === "available" ? t("Available", "已开放") : t("Coming later", "规划中"), { className: "evolution-module-badge" }));
    section.append(moduleHead);
    if (module.state === "available" && module.create) {
      const instance = module.create(context);
      moduleInstances.set(module.id, instance);
      moduleHead.append(instance.headerActions);
      section.append(instance.content);
    }
    modulesRoot.append(section);
  }
  let disposed = false;
  container.append(header, modulesRoot);
  root.append(sheet, container);
  parentSignal?.addEventListener("abort", dispose, { once: true });

  function dispose() {
    if (disposed) return;
    disposed = true;
    controller.abort();
    sheet.remove();
    container.remove();
    parentSignal?.removeEventListener("abort", dispose);
  }

  if (parentSignal?.aborted) dispose();
  else {
    for (const instance of moduleInstances.values()) instance.start();
  }
  return { dispose };
}

export default {
  apiVersion: 1,
  module: "skill-evolution.v1",
  surfaces: [
    {
      id: "status",
      slot: "page",
      title: "Agent self-evolution",
      navigation: {
        label: "Agent self-evolution",
        labelZh: "Agent 自演进",
      },
      mount,
    },
  ],
};
