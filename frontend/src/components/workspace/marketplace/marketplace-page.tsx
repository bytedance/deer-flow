"use client";

import { Search, Star, Download, Filter, Factory } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useMemo } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import type { MarketplaceListing } from "@/core/marketplace/api";
import { useMarketplaceListings } from "@/core/marketplace/hooks";

export function MarketplacePage() {
  const router = useRouter();
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>("");
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  const { listings, isLoading } = useMarketplaceListings({
    search: search || undefined,
    category: category || undefined,
    sort_by: sortBy,
    sort_order: sortOrder,
  });

  const categories = useMemo(() => {
    const cats = new Set<string>();
    for (const l of listings) {
      if (l.category) cats.add(l.category);
    }
    return Array.from(cats);
  }, [listings]);

  const featuredIndustrial = useMemo(() => {
    return listings.filter(
      (l) => l.is_featured && l.category === "industrial"
    );
  }, [listings]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="border-b px-6 py-4">
        <h1 className="text-lg font-semibold">{t.marketplace.title}</h1>
        <p className="text-sm text-muted-foreground">
          {t.marketplace.subtitle}
        </p>
      </header>

      {/* Featured Industrial Intelligence Section */}
      {featuredIndustrial.length > 0 && (
        <div className="border-b bg-accent/30 px-6 py-4">
          <div className="mb-3 flex items-center gap-2">
            <Factory className="h-5 w-5 text-primary" />
            <h2 className="text-sm font-semibold">
              {t.marketplace.industrialIntelligence}
            </h2>
            <Button
              variant="link"
              size="sm"
              className="ml-auto h-auto p-0 text-xs"
              onClick={() =>
                router.push("/workspace/template-marketplace/industrial")
              }
            >
              {t.marketplace.browseAllTemplates}
            </Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {featuredIndustrial.slice(0, 3).map((listing) => (
              <ListingCard
                key={listing.id}
                listing={listing}
                onClick={() =>
                  router.push(`/workspace/template-marketplace/${listing.id}`)
                }
                t={t}
                featured
              />
            ))}
          </div>
        </div>
      )}

      {/* Search and filters */}
      <div className="flex items-center gap-3 border-b px-6 py-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t.marketplace.searchPlaceholder}
            className="pl-9"
          />
        </div>

        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder={t.marketplace.category} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t.marketplace.allCategories}</SelectItem>
            {categories.map((cat) => (
              <SelectItem key={cat} value={cat}>
                {cat}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder={t.marketplace.sortBy} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="created_at">{t.marketplace.sortByNewest}</SelectItem>
            <SelectItem value="avg_rating">{t.marketplace.sortByRating}</SelectItem>
            <SelectItem value="install_count">{t.marketplace.sortByInstalls}</SelectItem>
          </SelectContent>
        </Select>

        <Button
          variant="outline"
          size="icon"
          onClick={() =>
            setSortOrder(sortOrder === "desc" ? "asc" : "desc")
          }
        >
          <Filter className="h-4 w-4" />
        </Button>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            {t.marketplace.loading}
          </div>
        ) : listings.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <p className="text-sm">{t.marketplace.noTemplates}</p>
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
                t={t}
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
  featured = false,
  t,
}: {
  listing: MarketplaceListing;
  onClick: () => void;
  featured?: boolean;
  t: Translations;
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
          <div className="flex items-center gap-1">
            {featured && (
              <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                {t.marketplace.featured}
              </span>
            )}
            {listing.category && (
              <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                {listing.category}
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="line-clamp-2 text-xs text-muted-foreground">
          {listing.description || t.marketplace.noDescription}
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
