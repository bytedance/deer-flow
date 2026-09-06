import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type RetrievalCatalogItem = {
  id: string;
  name: string;
  selectable: boolean;
};

export type RetrievalCatalogPage = {
  items: RetrievalCatalogItem[];
  page: number;
  page_size: number;
  total: number;
};

function catalogUrl(path: string): string {
  return `${getBackendBaseURL()}/api/knowledge/retrieval-catalog${path}`;
}

async function readCatalogPage(
  response: Response,
  fallback: string,
): Promise<RetrievalCatalogPage> {
  if (!response.ok) await throwGatewayApiError(response, fallback);
  return (await response.json()) as RetrievalCatalogPage;
}

export async function listRetrievalCatalogDatasets(options: {
  agentName: string;
  page: number;
  pageSize?: number;
  search?: string;
}): Promise<RetrievalCatalogPage> {
  const query = new URLSearchParams({
    agent_name: options.agentName,
    page: String(options.page),
    page_size: String(options.pageSize ?? 100),
  });
  if (options.search?.trim()) query.set("search", options.search.trim());
  const response = await fetch(catalogUrl(`/datasets?${query}`));
  return readCatalogPage(response, "Failed to load the retrieval catalog.");
}

export async function listRetrievalCatalogDocuments(options: {
  agentName: string;
  datasetId: string;
  page: number;
  pageSize?: number;
  search?: string;
}): Promise<RetrievalCatalogPage> {
  const query = new URLSearchParams({
    agent_name: options.agentName,
    page: String(options.page),
    page_size: String(options.pageSize ?? 100),
  });
  if (options.search?.trim()) query.set("search", options.search.trim());
  const response = await fetch(
    catalogUrl(
      `/datasets/${encodeURIComponent(options.datasetId)}/documents?${query}`,
    ),
  );
  return readCatalogPage(response, "Failed to load knowledge-base documents.");
}
