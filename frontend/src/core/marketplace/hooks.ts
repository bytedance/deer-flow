import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createMarketplaceReview,
  getMarketplaceListing,
  installMarketplaceTemplate,
  listMarketplaceListings,
  listMarketplaceReviews,
  publishToMarketplace,
} from "./api";

import type {
  CreateReviewRequest,
  InstallRequest,
  ListListingsParams,
  PublishToMarketplaceRequest,
} from "./api";

const MARKETPLACE_KEY = "marketplace" as const;

export function useMarketplaceListings(params?: ListListingsParams) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: [MARKETPLACE_KEY, "list", params],
    queryFn: () => listMarketplaceListings(params),
  });
  return { listings: data ?? [], isLoading, error, refetch };
}

export function useMarketplaceListing(id: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: [MARKETPLACE_KEY, "one", id],
    queryFn: () => getMarketplaceListing(id ?? ""),
    enabled: !!id,
  });
  return { listing: data, isLoading, error };
}

export function useMarketplaceReviews(listingId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: [MARKETPLACE_KEY, "reviews", listingId],
    queryFn: () => listMarketplaceReviews(listingId ?? ""),
    enabled: !!listingId,
  });
  return { reviews: data ?? [], isLoading, error };
}

export function useCreateMarketplaceReview(listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateReviewRequest) =>
      createMarketplaceReview(listingId, body),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: [MARKETPLACE_KEY, "reviews", listingId],
      });
    },
  });
}

export function useInstallMarketplaceTemplate(listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InstallRequest) =>
      installMarketplaceTemplate(listingId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [MARKETPLACE_KEY] });
      void qc.invalidateQueries({ queryKey: ["report-templates"] });
    },
  });
}

export function usePublishToMarketplace(templateId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PublishToMarketplaceRequest) =>
      publishToMarketplace(templateId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [MARKETPLACE_KEY] });
    },
  });
}
