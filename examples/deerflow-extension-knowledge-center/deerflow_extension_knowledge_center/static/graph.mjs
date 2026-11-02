// Deterministic, bounded SVG plus an equivalent keyboard-accessible list.
// No force simulation, external resources or inferred relations.
export function renderGraph(root, graph, { make, button, w }) {
  const entities = graph.entities ?? [],
    relations = graph.relations ?? [];
  if (entities.length > 200 || relations.length > 100)
    throw new Error("Graph exceeds supported bounds");
  root.append(make("p", w.graphNote, { class: "note" }));
  if (!entities.length && !relations.length) {
    root.append(make("p", w.empty));
    return;
  }
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 800 540");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", w.graphLabel);
  svg.setAttribute("class", "relation-graph");
  const positions = new Map();
  entities.forEach((entity, i) => {
    const angle = (2 * Math.PI * i) / entities.length;
    positions.set(entity.id, {
      x: 400 + 300 * Math.cos(angle),
      y: 270 + 210 * Math.sin(angle),
    });
  });
  for (const relation of relations) {
    const a = positions.get(relation.source),
      b = positions.get(relation.target);
    if (!a || !b) throw new Error("Missing graph endpoint");
    const line = document.createElementNS(ns, "line");
    Object.entries({ x1: a.x, y1: a.y, x2: b.x, y2: b.y }).forEach(
      ([key, value]) => line.setAttribute(key, String(value)),
    );
    svg.append(line);
  }
  for (const entity of entities) {
    const pos = positions.get(entity.id);
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", String(pos.x));
    circle.setAttribute("cy", String(pos.y));
    circle.setAttribute("r", "7");
    const title = document.createElementNS(ns, "title");
    title.textContent = entity.id;
    circle.append(title);
    svg.append(circle);
    if (entities.length <= 20) {
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", String(pos.x));
      label.setAttribute("y", String(pos.y - 14));
      label.setAttribute("text-anchor", "middle");
      label.textContent = entity.id.slice(0, 24);
      svg.append(label);
    }
  }
  const detail = make("div", "", { "aria-live": "polite" });
  detail.append(make("p", w.choose));
  const list = make("div", "", { class: "entity-list" });
  for (const entity of entities)
    list.append(
      button(entity.id, () => {
        detail.replaceChildren(
          make("h4", `${w.selected}: ${entity.id}`),
          make("p", entity.description),
        );
      }),
    );
  root.append(svg, list, detail);
  const evidence = new Map(
    (graph.evidence ?? []).map((item) => [item.id, item]),
  );
  for (const relation of relations) {
    const row = make("article");
    row.append(
      make("h4", `${relation.source} — ${relation.target}`),
      make("p", relation.description),
    );
    const ids = relation.evidence_ids ?? [];
    if (!ids.length) row.append(make("p", w.noEvidence, { class: "note" }));
    for (const id of ids) {
      if (!evidence.has(id)) throw new Error("Missing graph evidence");
      const block = make("details");
      block.append(
        make("summary", `${w.evidence} · ${id}`),
        make("pre", evidence.get(id).content),
      );
      block.open = relations.length === 1;
      row.append(block);
    }
    root.append(row);
  }
}
