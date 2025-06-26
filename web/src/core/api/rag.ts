import type { Resource } from "../messages";

import { resolveServiceURL } from "./resolve-service-url";

export function queryRAGResources(query: string) {
  return fetch(resolveServiceURL(`rag/resources?query=${query}`), {
    method: "GET",
  })
    .then((res) => res.json())
    .then((res) => {
      return res.resources as Array<Resource>;
    })
    .catch(() => {
      return [];
    });
}
