import type { JSONContent } from "@tiptap/react";

import type { ArtifactGroup } from "../types";

export function artifactToTiptapContent(artifact: ArtifactGroup): JSONContent {
  const content: JSONContent[] = [];

  // Metrics row (grouped)
  if (artifact.metrics.length > 0) {
    content.push({
      type: "metricRowNode",
      attrs: {
        metrics: artifact.metrics.map((m) => ({
          metricId: m.id,
          label: m.label,
          value: m.value,
          change: m.change ?? null,
        })),
      },
    });
  }

  // Charts with title headings
  for (const chart of artifact.charts) {
    content.push({
      type: "heading",
      attrs: { level: 3 },
      content: [{ type: "text", text: chart.title }],
    });

    content.push({
      type: "chartNode",
      attrs: {
        chartId: chart.id,
        title: chart.title,
        option: chart.option,
      },
    });
  }

  // Trailing empty paragraph for typing
  content.push({
    type: "paragraph",
  });

  return { type: "doc", content };
}
