import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

const PREFIX = "/api/template-marketplace";
const TEMPLATES_PREFIX = "/api/report-templates";

async function _gateway<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchGateway(`${getBackendBaseURL()}${path}`, init);
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = res.statusText;
    }
    const err = new Error(
      `Gateway ${init?.method ?? "GET"} ${path} failed: ${res.status} ${JSON.stringify(detail)}`,
    ) as Error & { status: number; detail: unknown };
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return (await res.json()) as T;
}

export interface MarketplaceListing {
  id: string;
  tenant_id: string;
  template_id: string;
  template_version: number;
  display_name: string;
  description: string;
  visibility: string;
  category: string | null;
  tags: string[] | null;
  icon: string | null;
  avg_rating: number;
  review_count: number;
  install_count: number;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface MarketplaceReview {
  id: string;
  listing_id: string;
  tenant_id: string;
  user_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

export interface InstallResult {
  id: string;
  listing_id: string;
  tenant_id: string;
  user_id: string;
  target_template_id: string;
  source_version: number;
  installed_at: string;
}

export interface PublishToMarketplaceRequest {
  display_name: string;
  description: string;
  visibility: string;
  category?: string;
  tags?: string[];
  icon?: string;
  requires_approval?: boolean;
}

export interface CreateReviewRequest {
  rating: number;
  comment?: string;
}

export interface InstallRequest {
  target_visibility: "private" | "tenant";
  target_name?: string;
}

export interface ListListingsParams {
  search?: string;
  category?: string;
  visibility?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export async function listMarketplaceListings(
  params?: ListListingsParams,
): Promise<MarketplaceListing[]> {
  const searchParams = new URLSearchParams();
  if (params?.search) searchParams.set("search", params.search);
  if (params?.category) searchParams.set("category", params.category);
  if (params?.visibility) searchParams.set("visibility", params.visibility);
  if (params?.sort_by) searchParams.set("sort_by", params.sort_by);
  if (params?.sort_order) searchParams.set("sort_order", params.sort_order);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return _gateway(`${PREFIX}${qs ? `?${qs}` : ""}`);
}

export async function getMarketplaceListing(
  id: string,
): Promise<MarketplaceListing> {
  return _gateway(`${PREFIX}/${id}`);
}

export async function listMarketplaceReviews(
  listingId: string,
): Promise<MarketplaceReview[]> {
  return _gateway(`${PREFIX}/${listingId}/reviews`);
}

export async function createMarketplaceReview(
  listingId: string,
  body: CreateReviewRequest,
): Promise<MarketplaceReview> {
  return _gateway(`${PREFIX}/${listingId}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function installMarketplaceTemplate(
  listingId: string,
  body: InstallRequest,
): Promise<InstallResult> {
  return _gateway(`${PREFIX}/${listingId}/install`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function publishToMarketplace(
  templateId: string,
  body: PublishToMarketplaceRequest,
): Promise<{ listing_id: string; status: string; message: string }> {
  return _gateway(
    `${TEMPLATES_PREFIX}/${templateId}/publish-to-marketplace`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function exportTemplatePackage(
  templateId: string,
  version?: number,
): Promise<Blob> {
  const qs = version != null ? `?version=${version}` : "";
  const res = await fetchGateway(
    `${getBackendBaseURL()}${TEMPLATES_PREFIX}/${templateId}/export${qs}`,
  );
  if (!res.ok) {
    throw new Error(`Export failed: ${res.status}`);
  }
  return await res.blob();
}

export async function importTemplatePackage(
  file: File,
  visibility: "private" | "tenant" = "private",
): Promise<{ template: { id: string; name: string; display_name: string } }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetchGateway(
    `${getBackendBaseURL()}${TEMPLATES_PREFIX}/import?visibility=${visibility}`,
    {
      method: "POST",
      body: formData,
    },
  );
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = res.statusText;
    }
    throw new Error(`Import failed: ${res.status} ${JSON.stringify(detail)}`);
  }
  return (await res.json()) as {
    template: { id: string; name: string; display_name: string };
  };
}
