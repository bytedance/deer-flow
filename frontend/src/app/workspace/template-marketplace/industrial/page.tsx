"use client";

import { useRouter } from "next/navigation";
import { Factory, Star, Download, ArrowLeft } from "lucide-react";

import { useMarketplaceListings } from "@/core/marketplace/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import type { MarketplaceListing } from "@/core/marketplace/api";

export default function IndustrialTemplatesPage() {
  const router = useRouter();
  const { listings, isLoading } = useMarketplaceListings({
    category: "industrial",
    sort_by: "install_count",
    sort_order: "desc",
  });

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="border-b px-6 py-4">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => router.push("/workspace/template-marketplace")}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2">
            <Factory className="h-6 w-6 text-primary" />
            <div>
              <h1 className="text-lg font-semibold">Industrial Intelligence</h1>
              <p className="text-sm text-muted-foreground">
                Templates for equipment monitoring, fault diagnosis, and trend analysis
              </p>
            </div>
          </div>
        </div>
      </header>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            Loading industrial templates...
          </div>
        ) : listings.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <Factory className="mb-4 h-12 w-12 opacity-20" />
            <p className="text-sm">No industrial templates found</p>
            <Button
              variant="link"
              className="mt-2"
              onClick={() => router.push("/workspace/template-marketplace")}
            >
              Browse all templates
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {listings.map((listing) => (
              <ListingCard
                key={listing.id}
                listing={listing}
                onClick={() =>
                  router.push(`/workspace/template-marketplace/${listing.id}`)
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ListingCard({
  listing,
  onClick,
}: {
  listing: MarketplaceListing;
  onClick: () => void;
}) {
  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-md"
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <h3 className="line-clamp-1 text-sm font-semibold">
            {listing.display_name}
          </h3>
          {listing.is_featured && (
            <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
              Featured
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="line-clamp-2 text-xs text-muted-foreground">
          {listing.description || "No description"}
        </p>

        {/* Stats */}
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Star className="h-3 w-3" />
            {listing.avg_rating.toFixed(1)}
            <span className="text-muted-foreground/60">
              ({listing.review_count})
            </span>
          </span>
          <span className="flex items-center gap-1">
            <Download className="h-3 w-3" />
            {listing.install_count}
          </span>
        </div>

        {/* Tags */}
        {listing.tags && listing.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {listing.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
